# Documentación - TalentPitch Recommendation Service

## 📚 Índice de Documentación

Esta carpeta contiene la documentación técnica completa del servicio de recomendaciones de TalentPitch.

### Documentos Principales

1. **[Resumen del Proyecto](project-summary.md)** 📋
   - Resumen ejecutivo del sistema
   - Stack tecnológico
   - Componentes principales
   - API endpoints
   - Configuración y deployment
   - Troubleshooting

2. **[Arquitectura](architecture.md)** 🏗️
   - Arquitectura detallada del sistema
   - Flujos de datos
   - Motor de recomendaciones (bandits contextuales)
   - Modelo de datos
   - Optimizaciones
   - Métricas de rendimiento

3. **[Guía de Desarrollo](development-guide.md)** 🛠️
   - Setup local
   - Convenciones de código
   - Testing y debugging
   - Git workflow
   - Deployment
   - Contributing

### Navegación Rápida

| Necesitas | Lee esto |
|-----------|----------|
| Entender qué es el proyecto | [Resumen del Proyecto](project-summary.md) |
| Conocer la arquitectura | [Arquitectura](architecture.md) |
| Empezar a desarrollar | [Guía de Desarrollo](development-guide.md) |
| Usar la API | [Resumen del Proyecto - API Endpoints](project-summary.md#-api-endpoints) |
| Debugging | [Guía de Desarrollo - Debugging](development-guide.md#-debugging) |
| Deploy | [Guía de Desarrollo - Deployment](development-guide.md#-deployment) |

---

## 🎯 Propósito

Esta documentación proporciona:

- **Visión general** del sistema y sus componentes
- **Arquitectura técnica** detallada
- **Guía práctica** para desarrolladores
- **Convenciones** de código y mejores prácticas
- **Procedimientos** de testing y deployment

---

## 📖 Cómo Usar Esta Documentación

### Para Nuevos Desarrolladores

1. Leer [Resumen del Proyecto](project-summary.md) para entender el sistema
2. Revisar [Arquitectura](architecture.md) para entender el diseño
3. Seguir [Guía de Desarrollo](development-guide.md) para setup local
4. Consultar específicos según necesidad

### Para Deployment

1. Ver [Resumen del Proyecto - Docker](project-summary.md#-docker)
2. Revisar [Guía de Desarrollo - Deployment](development-guide.md#-deployment)
3. Consultar variables de entorno en [Resumen del Proyecto - Configuración](project-summary.md#-configuración)

### Para Debugging

1. Revisar [Guía de Desarrollo - Debugging](development-guide.md#-debugging)
2. Ver [Resumen del Proyecto - Troubleshooting](project-summary.md#-troubleshooting)
3. Consultar logs según [Guía de Desarrollo - Ver Logs](development-guide.md#ver-logs)

---

## 🔗 Enlaces Útiles

### Documentación Relacionada

- [README Principal](../README.md)
- [Cursor Rules](../.cursorrules)
- [Dockerfile](../Dockerfile)
- [docker-compose.yml](../docker-compose.yml)

### Archivos de Ejemplo

- [endpoint_total.json](../api/endpoint_total.json)
- [endpoint_discover.json](../api/endpoint_discover.json)
- [endpoint_flow.json](../api/endpoint_flow.json)

### Configuración

- [requirements.txt](../requirements.txt)
- [.dockerignore](../.dockerignore)
- [credentials/.env](../credentials/.env) (ejemplo)

---

## 📝 Actualizaciones

Esta documentación se actualiza conforme el proyecto evoluciona.

**Última actualización**: 2025  
**Versión**: 2.0  
**Mantenedor**: TalentPitch Dev Team

---

## 🤝 Contribuir

Si encuentras información desactualizada o quieres agregar contenido:

1. Abre un issue con la sugerencia
2. O crea un PR con los cambios
3. Mantén el formato y estructura existente

---

## 📧 Soporte

Para dudas o problemas:

- Revisa los documentos correspondientes
- Consulta [Troubleshooting](project-summary.md#-troubleshooting)
- Abre un issue en el repositorio
- Contacta al equipo de desarrollo
