# TimeTrack

Reporte de horas personal en **Azure DevOps** y **SIGES** a partir de un texto en prosa.
Un agente de IA (API de Claude) interpreta el reporte, y código determinista valida,
muestra una vista previa y envía a ambos sistemas.

```
reporte.txt ──► Agente (Claude) ──► Plan ──► Validador (8 h/día) ──► Preview
                                                                      │ --apply
                                   Ledger ◄── Azure DevOps / SIGES ◄──┘
```

El modelo solo **extrae** (fecha, descripción, horas, incidente). Las fechas, las horas y el
envío los maneja el código: el agente nunca inventa horas ni habla directo con Azure o SIGES.

## Requisitos

- Python 3.12+
- `pip install anthropic pydantic requests`

## Variables de entorno

| Variable | Para qué |
|---|---|
| `AZURE_DEV_KEY` | PAT de Azure DevOps |
| `SIGES_USER` / `SIGES_PASS` | Credenciales de SIGES (login automático) |
| `ANTHROPIC_API_KEY` | API de Claude (agente) |
| `TIMETRACK_MODEL` | Opcional. Modelo del agente (por defecto `claude-haiku-5-5`) |

En PowerShell, solo para la terminal actual (no escriba la contraseña en el comando):

```powershell
$env:SIGES_USER = "su_usuario"
$env:SIGES_PASS = Read-Host "Password SIGES"
```

`azure/config.json` define `org`, `project`, `team`, `area`, `activity` y `sistema`
(y opcionalmente `fields` con campos requeridos del Bug). `azure/parent_task.json` es la
plantilla (`assignedTo`, `fields`) con la que se crean los Bugs nuevos.

## Uso

```powershell
python -m timetrack reporte.txt                            # dry-run: solo muestra qué enviaría
python -m timetrack reporte.txt --guardar-plan plan.json   # además guarda el plan interpretado
python -m timetrack reporte.txt --apply                    # envía (pide confirmación)
python -m timetrack plan.json --apply --yes                # plan ya armado, sin confirmación
```

La entrada puede ser un `.txt` (prosa) o un `.json` (plan, ver `tests/plan_ejemplo.json`).
**Siempre se hace primero un dry-run**; solo `--apply` escribe en Azure y SIGES.

| Opción | Efecto |
|---|---|
| `--apply` | Envía de verdad (por defecto es dry-run) |
| `--yes` | No pide confirmación |
| `--guardar-plan RUTA` | Guarda el plan interpretado en un `.json` |
| `--cerrar-dia` | Pide cerrar el día en SIGES* |

\* `siges/siges_service.py` fija `cerrarDia` en `"false"` a propósito (cerrar un día obliga a
pedirle al PM que lo reabra), por lo que esta opción no tiene efecto mientras ese valor esté fijo.

## Formato de la prosa

Una línea con la fecha (`dd-mm-yyyy`) abre cada día. Cada actividad empieza con el número de
incidente, o con `Fuera de incidente`, y termina con sus horas:

```
29-10-2026
Fuera de incidente, Soporte a errores presentados en QA con transferencias entre cuentas BN. 4
100001273 revisión de diferencias contables en SINPE Móvil, se revisan insumos de SFB y BCCR. 4
```

Reglas:
- **Cada día debe sumar exactamente 8 h**; si no, el programa se detiene antes de enviar nada.
- Si una actividad no trae horas, es un error (el agente no las reparte ni las estima).

## Qué se crea en cada sistema

**Azure DevOps** (el sprint se obtiene por la fecha con `get_iteration_for`):
- **Con incidente:** una sola Task hija **"DEV - Revisión SOA"** por (incidente, sprint), con las
  horas sumadas y las descripciones concatenadas por fecha.
- **Fuera de incidente:** una sola Task **"DEV - Joseph Ramirez"** por sprint, hija de
  "DEV - Tareas fuera de incidentes" (ese padre debe existir en el sprint).
- Si la Task ya existe, **se edita**: se suman las horas y se concatena la descripción.
- Si el incidente no existe en Azure, se pide el título y se crea el Bug.

**SIGES:** una línea por actividad, con la tarea fija `1000000000112368`, el `numIdent` derivado
del sprint (`Sprint 2026.22` → `SPR 22`) y el incidente antepuesto al comentario. Se envía por
día completo.

## Seguridad ante reenvíos

`data/ledger.json` registra lo ya enviado (Azure por actividad, SIGES por día), así que repetir
un `--apply` solo envía lo pendiente. **No lo borre** salvo que verifique antes en Azure y SIGES
que no habrá duplicados: como las ediciones suman horas, un reenvío sin ledger las duplicaría.
Cada entrada guarda también `enviado` (cuándo se envió) y `fecha` (el día de la tarea); el calendario del
Historial usa esta última. Las entradas de Azure anteriores a este campo no la tienen y se muestran en su
día de envío.
`data/catalog.json` es la caché local de incidentes ya resueltos (número → work item de Azure).

## Tareas de la semana

Lista personal local (`data/tareas.json`) con cuatro estados: `pendiente`, `en_proceso`, `entregada`
y `cerrada`. Cada tarea pertenece a una semana ISO (`2026-W45`, la actual por defecto).

```powershell
python -m timetrack.tareas_cli nueva "Revisar diferencias" --incidente 100001273
python -m timetrack.tareas_cli mover 1 en_proceso
python -m timetrack.tareas_cli listar            # semana actual, agrupado por estado (--todas, --estado, --semana)
python -m timetrack.tareas_cli resumen
python -m timetrack.tareas_cli editar 1 --titulo "Nuevo título" --notas "..."
python -m timetrack.tareas_cli eliminar 1
```

Con `--incidente`, la tarea se vincula a su Bug padre con la misma lógica del reporte: catálogo local →
búsqueda en Azure → si no existe, **crea el Bug** con el título de la tarea (sin preguntar; se antepone el número del incidente). Si Azure falla, no se guarda la tarea.
Sin incidente no se toca Azure. Los estados son solo locales: no se reflejan en Azure. La lógica está en
`timetrack/tareas.py` (`TaskStore`) para que el dashboard la use después.

## Pull Requests en Azure DevOps

Compara una branch con la principal de un repo de Azure DevOps y crea el Pull Request por API REST
(misma auth `AZURE_DEV_KEY` que el reporte; el PAT necesita además el scope **Code (Read & Write)**).
El repo se configura en `azure/config.json`:

```json
"repos": { "default": "nombre-o-id-del-repo-principal", "target_branch": "qa", "project": "opcional-si-es-otro-proyecto",
          "fork": "nombre-o-id-de-tu-fork", "fork_project": "opcional", "source_branch": "dev" }
```

`fork`, `fork_project` y `source_branch` son opcionales. Con `fork`, tu branch de origen se busca en el fork y el
PR se crea en el repo principal con `forkSource` (como un PR de fork a upstream). La comparación de commits va
contra la punta de la branch destino; si Azure no la permite, se muestra un aviso y el PR se puede crear igual.

```powershell
python -m timetrack.pr_cli estado --branch feature/mi-cambio          # commits por integrar y commits que te faltan
python -m timetrack.pr_cli crear --branch feature/mi-cambio --titulo "Mi cambio"          # previsualiza (dry-run)
python -m timetrack.pr_cli crear --branch feature/mi-cambio --titulo "Mi cambio" --apply  # crea el PR (--draft opcional)
```

Si ya hay un PR activo para esa branch y destino, se reutiliza en vez de duplicarlo. Código en
`azure/azure_repos_service.py` y `timetrack/pr_cli.py`. El dashboard tiene el módulo **Pull Requests**
(`/pullrequests/`, en `dashboard/app/modules/pullrequests/`): eliges la branch (autocompleta con las del repo),
ves los commits por integrar y los que te faltan, y creas el PR desde ahí.

## Dashboard web

Interfaz local para varios proyectos; el reporte de horas es su primer módulo.
Pegue la prosa → **Interpretar** → vista previa (Azure y SIGES) → **Enviar** → resultado con enlaces
a los work items. Además hay un **Historial** (calendario mensual del ledger por día de tarea, y catálogo; solo lectura).

```powershell
pip install -r dashboard\requirements.txt
uvicorn dashboard.app.main:app --host 127.0.0.1 --port 8000   # desde la raíz del proyecto
# abrir http://127.0.0.1:8000
```

Usa las mismas variables de entorno que el CLI (la terminal que lo lanza debe tenerlas definidas).
Reutiliza el núcleo de `timetrack` (`build_preview` / `execute`), así que el comportamiento es idéntico
al del CLI: mismas reglas de 8 h, mismo ledger, mismo dry-run previo.

Seguridad: escucha solo en localhost, rechaza `Host` ajenos y exige un token CSRF en toda petición que
escribe; cada vista previa se puede enviar una sola vez y se envía exactamente lo que se mostró.
No lo exponga fuera de su equipo: no tiene autenticación y puede escribir en Azure y SIGES.

### Apariencia

Bootstrap 5.3 e iconos de Bootstrap Icons (ambos en local, sin CDN) con un tema propio en
`dashboard/app/static/app.css`: menú superior, acento azul navy, tarjetas planas.
Tiene **modo claro y oscuro**: el botón de la luna/sol del menú alterna y recuerda la elección; la primera
vez sigue la preferencia del sistema. Para cambiar la identidad visual (colores, bordes) basta con editar
las variables de los dos bloques al inicio de `app.css` (`:root` para el claro y `[data-bs-theme="dark"]`).
El menú lista automáticamente cada módulo instalado y resalta el activo; cada módulo define su icono
(`icon="bi-clock-history"` en su `Module`, ver https://icons.getbootstrap.com/).

### Pestaña «Mi sprint» (reporte de horas)

En `/horas/sprint` se escribe un número de sprint (`22`, o `2026.22`) y se listan **sus Tasks** de ese sprint
agrupadas por la tarea padre: título, descripción (en texto plano), estado y horas (estimado, completado,
restante), con enlaces a Azure y totales. Sin año usa el del año actual (o el más reciente que tenga ese número).
Es solo lectura. Solo muestra Tasks asignadas a usted (la consulta usa el mismo filtro de `get_sprint_ids`);
los Bugs u otros tipos no aparecen. La lógica pura está en `timetrack/sprint.py`.

### Instalar como aplicación (PWA)

El dashboard es una PWA: en Chrome o Edge, abierto en `http://127.0.0.1:8000`, use el ícono de instalar de la barra
de direcciones (o menú ⋮ → *Instalar TimeTrack*). Queda con ventana propia, ícono y atajos (Reporte de horas, Tareas,
Utilidades) en el menú Inicio. Solo funciona en `localhost`/`127.0.0.1` (necesita contexto seguro y el dashboard no
tiene autenticación: no lo exponga a la red).

**Necesita el servidor corriendo.** Instalarlo no lo hace funcionar sin conexión: los datos y la lógica viven en
`uvicorn`. Sin servidor, la app muestra «Servidor no disponible». Para no arrancarlo a mano:

```powershell
dashboard\iniciar.cmd           # doble clic: inicia el servidor en segundo plano, sin ventana (registro en data/dashboard.log)
powershell -File dashboard\detener.ps1   # lo detiene (solo si el proceso es de Python)
```

Para que arranque al iniciar sesión (no se registra solo; usted decide): `Win + R` → `shell:startup` y ponga ahí un
acceso directo a `dashboard\iniciar.cmd`. Ojo: un proceso en segundo plano solo ve las variables de entorno
**persistentes** (`AZURE_DEV_KEY`, `SIGES_USER`, `SIGES_PASS`, `ANTHROPIC_API_KEY`), no las puestas con `$env:` en una
terminal; guardar `SIGES_PASS` de forma persistente es una decisión de seguridad suya.

Detalles técnicos: el service worker (`/sw.js`) cachea solo estáticos y **nunca las páginas HTML**, porque cada arranque
genera un token CSRF nuevo incrustado en ellas (una página cacheada daría 403 en todos los POST); tampoco intercepta
POST ni fragmentos HTMX. Al cambiar sus reglas o la lista de precarga, suba `CACHE` en `dashboard/app/static/pwa/sw.js`.
Los íconos se regeneran con `python dashboard/tools/generar_iconos.py` (Pillow).

### Módulo «Utilidades»

Pestaña **Utilidades** (`/utilidades/`) con herramientas de texto y datos; todo se calcula en local salvo la última:

| Herramienta | Qué hace |
|---|---|
| JSON | Formatear, minificar, validar (con línea/columna) y comparar dos JSON por ruta (ignora el orden de claves) |
| XML | Formatear, minificar, validar y comparar dos XML (namespaces resueltos; sin DTD ni entidades, por seguridad) |
| Base64 | Codificar/decodificar texto UTF-8, con variante URL-safe |
| JWT | Decodificar encabezado y payload y ver si expiró. **No verifica la firma** |
| Timestamp | Unix timestamp ↔ fecha (segundos o milisegundos; Costa Rica y UTC) |
| Fechas | Convertir fecha y hora entre zonas horarias; avisa si la hora es ambigua por cambio de horario |
| Armar mensaje (IA) | Un agente llena un esquema (fragmento XSD/NXSD, en cualquier forma) con sus datos y devuelve XML o JSON |

**Armar mensaje** usa la API de Claude (`ANTHROPIC_API_KEY`; modelo con `UTILIDADES_MODEL`, por defecto
`claude-sonnet-5-5`). **Los fragmentos se envían a Anthropic: use datos ficticios o anonimizados.** El modelo mapea y el
código verifica: la salida debe ser XML/JSON válido (un reintento si no) y se avisa de valores de los datos que no
aparecen, valores que no vienen de los datos ni del esquema, y elementos que el esquema no declara. No es una validación
formal contra el XSD: revise el resultado. Nada se guarda ni se registra.

### Módulo «Tareas»

Pestaña **Tareas** (`/tareas/`): las tareas de `data/tareas.json` como post-its de color por estado
(amarillo pendiente, azul en proceso, verde entregada). Se **arrastran entre columnas** para cambiar de estado
y al **basurero** para cerrarlas; las cerradas dejan de mostrarse (siguen en el archivo). Se muestran todas las
abiertas, sin filtro por semana. En pantallas táctiles, o sin arrastrar, cada nota trae botones ← → y ✕.
«Pegar nota» crea una tarea; con un incidente nuevo crea su Bug en Azure usando el título de la tarea.
Mismas reglas que el CLI (`timetrack/tareas.py`), así que ambos ven los mismos datos.

### Agregar otro proyecto como módulo

Cree `dashboard/app/modules/<nombre>/` con un `__init__.py` que defina `module = Module(...)`
(ver `modules/horas/__init__.py`): nombre de URL, título, un `APIRouter`, su carpeta de plantillas y
opcionalmente una función `summary()` con las líneas de su tarjeta en la portada. Se descubre solo al arrancar.

### Migrar el dashboard a otra carpeta o repositorio

`dashboard/` depende de `timetrack/`, y `timetrack/` nunca importa `dashboard/`. Para migrarlo:
1. Mueva la carpeta `dashboard/` al nuevo proyecto (Bootstrap, Bootstrap Icons y htmx ya están incluidos en `app/static/vendor`, sin depender de un CDN).
2. Haga disponible `timetrack/` (y `azure/`, `siges/`, que usa a través de `timetrack.gateways`): copie esas
   carpetas junto a `dashboard/`, o conviértalas en un paquete instalable.
3. Los datos (`data/ledger.json`, `data/catalog.json`) son relativos a `timetrack/`; cópielos con él para
   conservar el historial y evitar reenvíos.
4. Ejecute las pruebas del dashboard para confirmar que todo sigue enlazado.

## Estructura

```
timetrack/
  agent.py        prosa → Plan (API de Claude, salida estructurada)
  models.py       Plan, Dia, Actividad (pydantic)
  validate.py     8 h por día, fechas sin repetir
  resolver.py     incidente → work item: catálogo → Azure → crear Bug
  catalog.py      caché local de incidentes
  adapters/       Plan → formato de Azure / de SIGES (sin red)
  pipeline.py     validar → preview → confirmar → enviar → ledger
  gateways.py     conexión real con los servicios
  ledger.py       registro de lo enviado
  cli.py          punto de entrada (python -m timetrack)
azure/            cliente de Azure DevOps y su configuración
siges/            cliente de SIGES
data/             ledger.json y catalog.json (locales, fuera de git)
tests/            pruebas unitarias y ejemplos
dashboard/        dashboard web (FastAPI + HTMX), módulos enchufables en app/modules/
  app/            main, registro de módulos, seguridad, jobs, plantillas, estáticos
  tests/          pruebas del dashboard
```

## Pruebas

```powershell
python -m unittest discover -s tests -t . -v             # núcleo (CLI, agente, adaptadores, pipeline)
python -m unittest discover -s dashboard/tests -t . -v   # dashboard
```

Las pruebas no usan red ni escriben en `data/`: los gateways y el cliente de Claude se reemplazan por dobles.

## Limitaciones conocidas

- Dos actividades idénticas (misma descripción, horas e incidente) en un mismo día cuentan como una
  en el ledger.
- No hay opción para enviar a un solo sistema.
- No se ha confirmado qué devuelve SIGES ante un error (hoy HTTP 200 cuenta como éxito) ni si
  `Grabar_Tareas` reemplaza o agrega las tareas del día.
