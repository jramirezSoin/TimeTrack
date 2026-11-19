"""Repos de Azure DevOps: commits pendientes entre branches y Pull Requests (REST api-version 7.1).

Reutiliza la autenticación (PAT en AZURE_DEV_KEY) y los helpers de azure_devops_service.

azure/config.json -> "repos":
  default        repo principal (destino del PR): nombre o id
  target_branch  branch destino en el principal (por defecto "main")
  project        proyecto del repo principal, si no es el de "project"
  fork           (opcional) repo fork donde vive tu branch de origen: nombre o id
  fork_project   (opcional) proyecto del fork, si es distinto al del principal
  source_branch  (opcional) branch de origen por defecto
  reviewers      (opcional) reviewers del PR: correo, nombre o GUID de usuario/grupo de Azure DevOps
                 (correo/nombre se resuelven a GUID con la API de identidades; requiere PAT con Identity: Read)
Con "fork", el PR se crea en el repo principal con `forkSource` apuntando al fork.
"""
import re
from urllib.parse import quote

import azure_devops_service as _ado

API = "api-version=7.1"
_GUID_RE = re.compile(r"^[0-9a-fA-F]{8}-([0-9a-fA-F]{4}-){3}[0-9a-fA-F]{12}$")
_repos_cfg = _ado.config.get("repos", {})
_id_cache = {}


def _project():
    return _repos_cfg.get("project") or _ado.PROJECT


def _base(project=None):
    return f"https://dev.azure.com/{_ado.ORG}/{quote(project or _project())}"


def default_repo():
    repo = _repos_cfg.get("default")
    if not repo:
        raise RuntimeError('Falta "repos.default" (repo principal) en azure/config.json.')
    return repo


def default_target():
    return _repos_cfg.get("target_branch", "main")


def default_source():
    return _repos_cfg.get("source_branch", "")


def default_reviewers():
    """Reviewers de "repos.reviewers" (GUID, correo o nombre); acepta un string o una lista."""
    r = _repos_cfg.get("reviewers") or []
    return [r] if isinstance(r, str) else list(r)


def _reviewer_id(reviewer):
    """GUID del reviewer; si viene un correo o nombre se busca en Azure DevOps (una vez, en caché)."""
    if _GUID_RE.match(reviewer):
        return reviewer
    key = ("reviewer", reviewer.lower())
    if key not in _id_cache:
        url = (f"https://vssps.dev.azure.com/{_ado.ORG}/_apis/identities?searchFilter=General"
               f"&filterValue={quote(reviewer, safe='')}&{API}")
        found = _ado.ado_fetch(url).get("value", [])
        if len(found) > 1:  # varias coincidencias: quedarse con la exacta (correo o nombre)
            exact = [i for i in found if reviewer.lower() in (
                (i.get("properties", {}).get("Mail", {}).get("$value") or "").lower(),
                (i.get("providerDisplayName") or "").lower())]
            found = exact or found
        if len(found) != 1:
            motivo = "no se encontró" if not found else f"hay {len(found)} coincidencias para"
            raise RuntimeError(f'Reviewer "{reviewer}": {motivo} esa persona o grupo en Azure DevOps. '
                               "Usa el correo completo o el GUID.")
        _id_cache[key] = found[0]["id"]
    return _id_cache[key]


def _fork():
    return _repos_cfg.get("fork")


def _repo_url(repo):
    return f"{_base()}/_apis/git/repositories/{quote(repo or default_repo(), safe='')}"


def _fork_url():
    project = _repos_cfg.get("fork_project") or _project()
    return f"{_base(project)}/_apis/git/repositories/{quote(_fork(), safe='')}"


def _source_url(repo):
    """Repo donde vive la branch de origen: el fork si está configurado, si no el principal."""
    return _fork_url() if _fork() else _repo_url(repo)


def _fork_id():
    """GUID del fork (forkSource lo exige); se resuelve una vez aunque en config esté el nombre."""
    fork = _fork()
    if fork not in _id_cache:
        _id_cache[fork] = _ado.ado_fetch(f"{_fork_url()}?{API}")["id"]
    return _id_cache[fork]


def _branch(name):
    return name.removeprefix("refs/heads/")


def list_branches(repo=None):
    """Branches de origen disponibles (las del fork si hay fork)."""
    res = _ado.ado_fetch(f"{_source_url(repo)}/refs?filter=heads/&{API}")
    return [r["name"].removeprefix("refs/heads/") for r in res["value"]]


def _head_commit(repo_url, branch):
    res = _ado.ado_fetch(f"{repo_url}/refs?filter=heads/{quote(branch, safe='/')}&{API}")
    for r in res["value"]:
        if r["name"] == f"refs/heads/{branch}":
            return r["objectId"]
    raise RuntimeError(f"No existe la branch '{branch}'.")


def _commits(repo_url, item, compare, top):
    """Commits alcanzables desde `item` y no desde `compare` (cada uno: {"version", "versionType"}).

    commitsbatch recorre desde compareVersion y excluye itemVersion (verificado contra Azure),
    así que se envían invertidos para obtener "item menos compare".
    """
    body = {"itemVersion": compare, "compareVersion": item, "$top": top}
    res = _ado.ado_fetch(f"{repo_url}/commitsbatch?{API}", method="POST", body=body)
    return [
        {
            "id": c["commitId"],
            "short": c["commitId"][:8],
            "autor": c.get("author", {}).get("name", ""),
            "fecha": c.get("author", {}).get("date", ""),
            "mensaje": c.get("comment", "").splitlines()[0] if c.get("comment") else "",
        }
        for c in res.get("value", [])
    ]


def _br(name):
    return {"version": name, "versionType": "branch"}


def _sha(sha):
    return {"version": sha, "versionType": "commit"}


def commits_status(source, target=None, repo=None, top=100):
    """Compara `source` con `target`.

    ahead:  commits de source que aún no están en target (los que irían en el PR).
    behind: commits de target que le faltan a source.
    Con fork, source y target viven en repos distintos: se compara contra el commit de la punta del
    destino, dentro del fork (los forks de Azure DevOps comparten objetos). Si esa comparación falla,
    se devuelve `aviso` y el PR aún se puede crear.
    """
    source, target = _branch(source), _branch(target or default_target())
    if _fork():
        out = {"source": source, "target": target, "ahead_count": 0, "behind_count": 0,
               "ahead": [], "behind": []}
        try:
            head = _head_commit(_repo_url(repo), target)
            fork = _fork_url()
            out["ahead"] = _commits(fork, _br(source), _sha(head), top)
            out["behind"] = _commits(fork, _sha(head), _br(source), top)
            out["ahead_count"], out["behind_count"] = len(out["ahead"]), len(out["behind"])
        except RuntimeError as e:
            out["aviso"] = f"No se pudo comparar los commits entre el fork y el repo principal: {e}"
        return out

    base = _repo_url(repo)
    stats = _ado.ado_fetch(
        f"{base}/stats/branches?name={quote(source, safe='')}"
        f"&baseVersion={quote(target, safe='')}&baseVersionType=branch&{API}"
    )
    return {
        "source": source,
        "target": target,
        "ahead_count": stats.get("aheadCount", 0),
        "behind_count": stats.get("behindCount", 0),
        "ahead": _commits(base, _br(source), _br(target), top) if stats.get("aheadCount") else [],
        "behind": _commits(base, _br(target), _br(source), top) if stats.get("behindCount") else [],
    }


def find_active_pr(source, target=None, repo=None):
    source, target = _branch(source), _branch(target or default_target())
    url = (
        f"{_repo_url(repo)}/pullrequests?"
        f"searchCriteria.sourceRefName={quote('refs/heads/' + source, safe='')}"
        f"&searchCriteria.targetRefName={quote('refs/heads/' + target, safe='')}"
        f"&searchCriteria.status=active&{API}"
    )
    if _fork():
        url += f"&searchCriteria.sourceRepositoryId={_fork_id()}"
    prs = _ado.ado_fetch(url).get("value", [])
    return prs[0] if prs else None


def _my_id():
    """GUID del usuario dueño del PAT (se resuelve una vez)."""
    if "me" not in _id_cache:
        res = _ado.ado_fetch(f"https://dev.azure.com/{_ado.ORG}/_apis/connectionData")
        _id_cache["me"] = res["authenticatedUser"]["id"]
    return _id_cache["me"]


def _vs_url(pr, repo=None):
    """URL estilo https://<org>.visualstudio.com/<proyecto>/_git/<repo>/pullrequest/<id> (nombres, no GUIDs)."""
    r = pr.get("repository") or {}
    repo_name = r.get("name")
    if not repo_name:
        return pr_url(pr["pullRequestId"], repo)
    project = (r.get("project") or {}).get("name") or _project()
    return (f"https://{_ado.ORG.lower()}.visualstudio.com/{quote(project)}"
            f"/_git/{quote(repo_name, safe='')}/pullrequest/{pr['pullRequestId']}")


def list_my_active_prs(repo=None):
    """PRs activos creados por mí en el repo principal, del más reciente al más antiguo."""
    url = (f"{_repo_url(repo)}/pullrequests?searchCriteria.status=active"
           f"&searchCriteria.creatorId={_my_id()}&{API}")
    prs = _ado.ado_fetch(url).get("value", [])
    out = [
        {
            "id": p["pullRequestId"],
            "titulo": p.get("title", ""),
            "source": _branch(p.get("sourceRefName", "")),
            "target": _branch(p.get("targetRefName", "")),
            "draft": bool(p.get("isDraft")),
            "fecha": p.get("creationDate", ""),
            "url": _vs_url(p, repo),
            "reviewers": [{"nombre": r.get("displayName", ""), "voto": r.get("vote", 0)}
                          for r in p.get("reviewers", [])],
        }
        for p in prs
    ]
    return sorted(out, key=lambda p: p["fecha"], reverse=True)


def pr_url(pr_id, repo=None):
    return f"{_base()}/_git/{quote(repo or default_repo(), safe='')}/pullrequest/{pr_id}"


def create_pull_request(source, title, target=None, description="", repo=None,
                        reviewers=None, draft=False):
    """Crea el PR en el repo principal; si ya hay uno activo source->target, lo devuelve sin duplicar."""
    source, target = _branch(source), _branch(target or default_target())
    existing = find_active_pr(source, target, repo)
    if existing:
        return {"id": existing["pullRequestId"], "url": pr_url(existing["pullRequestId"], repo),
                "creado": False}
    body = {
        "sourceRefName": f"refs/heads/{source}",
        "targetRefName": f"refs/heads/{target}",
        "title": title,
        "description": description,
        "isDraft": draft,
    }
    if _fork():
        body["forkSource"] = {"name": f"refs/heads/{source}", "repository": {"id": _fork_id()}}
    reviewers = default_reviewers() if reviewers is None else reviewers
    if reviewers:
        body["reviewers"] = [{"id": _reviewer_id(r)} for r in reviewers]
    pr = _ado.ado_fetch(f"{_repo_url(repo)}/pullrequests?{API}", method="POST", body=body)
    return {"id": pr["pullRequestId"], "url": pr_url(pr["pullRequestId"], repo), "creado": True}
