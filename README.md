# PARKSIM — Simulador interactivo de parqueaderos

Aplicación de escritorio en Python para estudiar el problema de colas del laboratorio de parqueaderos. La interfaz se construye con Tkinter y las gráficas se muestran dentro de la misma ventana con Matplotlib. Todas las pestañas tienen desplazamiento vertical para recorrer el contenido completo.

## 1. Requisitos
- Python 3.10 o superior.
- pip.
- Windows, macOS o Linux con entorno gráfico.

## 2. Instalación en VS Code
Abre esta carpeta en VS Code. En la terminal ejecuta:

```bash
python -m venv .venv
```

En Windows:

```powershell
.venv\Scripts\activate
```

En macOS/Linux:

```bash
source .venv/bin/activate
```

Instala las dependencias:

```bash
pip install -r requirements.txt
```

## 3. Ejecutar

```bash
python main.py
```

## 4. Secciones de la aplicación
1. **Inicio:** contexto, parámetros y nota metodológica.
2. **Simulación:** número de cajeros, duración, réplicas y semilla.
3. **Resultados:** estadísticas por cajero, IC del 95%, composición de usuarios y criterio de decisión.
4. **Estado transitorio:** promedio móvil y corte estimado por cajero.
5. **Verificación y validación:** pruebas de lógica y contraste teórico M/M/1 por categoría.
6. **Exportar:** CSV, JSON y gráficas PNG para el informe.

### Navegación por las pestañas
- Usa la barra de desplazamiento vertical ubicada a la derecha de cada pestaña.
- También puedes girar la rueda del ratón sobre el contenido para subir o bajar.
- Las gráficas tienen mayor altura para facilitar la lectura de títulos, ejes y leyendas.

## 5. Parámetros tomados del enunciado
| Tipo | Servicio medio | Intervalo medio entre llegadas | Porcentaje |
|---|---:|---:|---:|
| Rápido | 1 min | 3 min | 25 % |
| Normal | 3 min | 3 min | 20 % |
| Lento | 4 min | 5 min | 27,5 % |
| Muy lento | 6 min | 7 min | 27,5 % |

## 6. Hipótesis de simulación (leer antes de interpretar)
El enunciado entrega simultáneamente porcentajes de usuarios y tiempos medios entre llegadas para cada categoría, pero no especifica cómo se combinan esos dos datos en cada una de las tres filas. Para tener un experimento reproducible, esta versión adopta una hipótesis explícita:

- Cada cajero conserva su propia fila FIFO e independiente.
- Cada fila recibe llegadas según un proceso exponencial con intervalo medio ponderado: `0.25*3 + 0.20*3 + 0.275*5 + 0.275*7 = 4.55 minutos`.
- A cada llegada se le asigna un tipo de usuario según los porcentajes 25 %, 20 %, 27,5 % y 27,5 %.
- El tiempo de servicio se genera con distribución exponencial y la media correspondiente al tipo asignado.
- No hay cambio de fila ni abandono.

Como el tiempo de servicio es una mezcla de distribuciones exponenciales, la fila agregada no es estrictamente M/M/1 homogénea; se interpreta como una cola M/G/1 de servicio mixto. Por eso la aplicación muestra por separado los cálculos teóricos M/M/1 de cada categoría. No se deben confundir ambos resultados. El escenario alternativo de 3/4/5 cajeros es exploratorio y supone reparto uniforme de la demanda total, por lo que cambia la hipótesis de filas independientes sin cambio.

El tipo **Normal** tiene `lambda = 1/3`, `mu = 1/3` y `rho = 1`. Su modelo M/M/1 está en condición crítica y no tiene métricas de estado estable finitas. La aplicación lo señala y no inventa valores teóricos de espera para ese caso.

## 7. Período de calentamiento
Se utiliza una regla gráfica basada en el promedio móvil del tiempo en sistema. El primer tramo que permanece dentro de una banda del 5 % alrededor del promedio móvil final durante varias ventanas se toma como corte estimado. Es una heurística para apoyar el análisis, no una demostración matemática de estado estable. Revisa las gráficas y documenta la decisión final en el informe.

## 8. Verificación, calibración y validación
- **Verificación:** pruebas de porcentajes, parámetros positivos, FIFO y reproducibilidad de semilla.
- **Calibración:** requiere datos reales de llegadas y tiempos de servicio del parqueadero. Como el enunciado no aporta registros reales, no se afirma que exista calibración empírica.
- **Validación:** comparación de los casos M/M/1 estables con fórmulas teóricas; el caso Normal (`rho = 1`) se reporta como crítico.

## 9. Reproducibilidad
La semilla aleatoria permite repetir el mismo experimento con los mismos parámetros. Registra duración, número de réplicas y semilla en el informe.

## 10. GitHub
Antes de subir el proyecto, puedes agregar un `.gitignore` para excluir `.venv/`, `__pycache__/` y resultados temporales. Los archivos exportados por el programa se guardan en la carpeta que elijas.
