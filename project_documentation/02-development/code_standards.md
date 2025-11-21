# Code Standards

Reglas de programación para el proyecto TalentPitch Recommendation Service.

## Estructura y estilo

- Sin comentarios ni emojis
- Imports al inicio ordenados: stdlib, third-party, local, separados por línea en blanco
- Docstrings en español con formato Google
- Type hints obligatorios en todas las funciones, métodos y atributos de clase
- Nombres descriptivos que hagan el código auto-documentado
- Máximo 80-100 caracteres por línea

## Configuración y variables

- Prohibido hardcodear valores: URLs, API keys, credenciales, paths, timeouts, etc.
- Todas las variables de configuración deben estar en archivo .env
- Usar python-dotenv o pydantic-settings para cargar variables de entorno
- Validar variables de entorno al inicio de la aplicación
- Proporcionar archivo .env.example con variables vacías o de ejemplo

## Arquitectura

- Dependency injection: pasar dependencias por constructor o parámetros, nunca acceso global
- Separación de responsabilidades: cada clase/función una única responsabilidad (SRP)
- Inmutabilidad por defecto: usar `dataclasses(frozen=True)` o `NamedTuple` cuando sea posible
- Composición sobre herencia
- Factory functions para instanciar objetos con dependencias complejas

## Manejo de errores

- Validación temprana: fallar rápido con excepciones específicas
- Nunca silenciar excepciones con `except Exception: pass`
- Logging estructurado con niveles apropiados (DEBUG, INFO, WARNING, ERROR)
- Propagar errores hacia arriba, manejar solo donde tenga sentido

## Testing y mantenibilidad

- Código testeable: funciones puras cuando sea posible
- Evitar estado compartido y efectos secundarios ocultos
- Interfaces claras que permitan mocking
- Evitar dependencias circulares

## Patrones recomendados

- Repository pattern para acceso a datos
- Strategy pattern para algoritmos intercambiables
- Factory pattern para creación de objetos complejos
- Evitar singleton, usar módulos de Python como singleton natural si es necesario
