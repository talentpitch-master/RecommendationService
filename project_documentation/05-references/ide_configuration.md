# TalentPitch Search Service - Cursor Rules

## Project Overview
Python-based recommendation service for TalentPitch platform. Implements contextual bandits (LinUCB) for personalized content feeds with infinite scroll capabilities.

## Tech Stack
- **Language**: Python 3.13 (Alpine)
- **Framework**: FastAPI + Gunicorn + Uvicorn
- **Database**: MySQL via SSH tunnel
- **Cache**: Redis via SSH tunnel with SSL
- **Data Processing**: Pandas, NumPy, SciPy
- **Containerization**: Docker
- **Patterns**: Singleton, Factory, Strategy

## Architecture

### Core Components
1. **DataService** - Singleton for loading/g managing MySQL data in memory
2. **RecommendationEngine** - Singleton with Contextual Bandits (LinUCB) algorithm
3. **ActivityTracker** - Singleton for Redis activity logging with auto-flush to MySQL
4. **Config** - Singleton for centralized configuration management

### Data Flow
- Data loaded from MySQL at startup into DataFrames (users, videos, interactions, connections, flows)
- Recommendations generated using contextual bandits with 5 pools: VMP, NU, AU, FLOWS, EXPLORE
- User activities tracked in Redis with TTL (24h for activities, 1h for sessions)
- Auto-flush to MySQL when 50+ activities accumulated or every 15 minutes

### Recommendation Patterns
- **VMP** (Most Valued Products): High-rated popular content
- **AU** (Affine to User): Personalized based on skills/interests
- **NU** (New): Recent content (<45 days)
- **FW** (Flows): Challenges/opportunities
- **EXPLORE**: Random exploration boost

## Code Style & Conventions

### Python Code
- **Docstrings**: Write comprehensive docstrings in Spanish with triple quotes
- **Naming**: snake_case for variables and functions
- **Type Hints**: Include type hints where applicable
- **Comments**: Use Spanish for inline comments explaining complex logic
- **Imports**: Group imports: stdlib, third-party, local

### Code Organization
```python
# Standard import order
import os
import sys
import time
import json

import pandas as pd
import numpy as np
from fastapi import FastAPI

from core.config import Config
from utils.logger import LoggerConfig
```

### Function Structure
```python
def funcion_ejemplo(parametro1, parametro2):
    """
    Descripcion breve de la funcion.
    
    Args:
        parametro1 (type): Descripcion
        parametro2 (type): Descripcion
    
    Returns:
        (type): Descripcion del retorno
    
    Notes:
        Consideraciones importantes
    """
    # Implementation
    pass
```

## Design Patterns to Use

### Singleton Pattern
Use for:
- `Config` - Centralized configuration
- `DataService` - Single data provider
- `RecommendationEngine` - Single recommender instance
- `MySQLConnection` - Single DB connection
- `RedisConnection` - Single cache connection
- `ActivityTracker` - Single tracking instance
- `LoggerConfig` - Single logger config

Implementation:
```python
class MyClass:
    _instance = None
    _initialized = False
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(MyClass, cls).__new__(cls)
        return cls._instance
    
    def __init__(self):
        if MyClass._initialized:
            return
        MyClass._initialized = True
        # Init logic here
```

### Factory Pattern
Use for dependency injection:
```python
def get_data_service():
    """Returns singleton DataService instance"""
    global _data_service_instance
    if _data_service_instance is None:
        _data_service_instance = DataService(MySQLConnection)
        _data_service_instance.load_all_data()
    return _data_service_instance
```

## File Structure

### Project Layout
```
RecommendationService/
├── api/                 # FastAPI endpoints and server
├── core/               # Core services (cache, config, database)
├── services/           # Business logic (data, recommendation, tracking)
├── utils/              # Utilities (logger)
├── data/               # Data files (blacklist.csv)
├── credentials/        # .env and SSH keys (NOT VERSIONED)
├── logs/               # Application logs (NOT VERSIONED)
├── main.py            # Entry point
├── Dockerfile         # Container definition
├── docker-compose.yml # Local development
└── requirements.txt   # Dependencies
```

## Environment Configuration

### .env Structure (credentials/.env)
```ini
# Environment selection
ENVIRONMENT=staging  # or prod

# SSH tunnel config
SSH_HOST=<host>
SSH_USER=<user>

# Redis config
REDIS_HOST=<host>
REDIS_PASSWORD=<pass>
REDIS_PORT=<port>
REDIS_SCHEME=<tls|redis>

# MySQL staging
STG_MYSQL_HOST=<host>
STG_MYSQL_USER=<user>
STG_MYSQL_PASSWORD=<pass>
STG_MYSQL_DB=<db>
STG_MYSQL_PORT=<port>

# MySQL production
PROD_MYSQL_HOST=<host>
PROD_MYSQL_USER=<user>
PROD_MYSQL_PASSWORD=<pass>
PROD_MYSQL_DB=<db>
PROD_MYSQL_PORT=<port>

# API config
API_HOST=0.0.0.0
API_PORT=5002

# Flush config
FLUSH_INTERVAL_SECONDS=900
FLUSH_THRESHOLD_ACTIVITIES=50
```

### Environment Selection
- `ENVIRONMENT=staging` → Uses `STG_*` prefixed variables
- `ENVIRONMENT=prod` → Uses `PROD_*` prefixed variables

## API Endpoints

### Standard Response Format
```json
{
    "statusCode": 200,
    "body": {
        "mix_ids": [...],
        "items": [...]
    }
}
```

### Key Endpoints
1. **POST /api/search/total** - Mixed feed (24 items) with VMP-AU-AU-VMP-NU-FW pattern
2. **POST /api/search/discover** - Resume-only feed (24 items)
3. **POST /api/search/flow** - Challenge-only feed (24 items)
4. **POST /api/search/reload** - Reload data from MySQL without restart

### Backward Compatibility
Support multiple parameter names:
- `user_id` / `SELF_ID`
- `excluded_ids` / `LAST_IDS` / `videos_excluidos`
- `size` / `MAX_SIZE`

## Database Queries

### Query Best Practices
```python
# Always use DictCursor
cursorclass=pymysql.cursors.DictCursor

# Set appropriate timeouts
connect_timeout=30
read_timeout=60
write_timeout=60

# Use parameterized queries
query = "SELECT * FROM users WHERE id = %s"
results = conn.execute_query(query, (user_id,))
```

### Blacklist Implementation
- Load blacklist from `data/blacklist.csv` at startup
- Apply in SQL WHERE clause for videos and flows
- Filter URLs at query level for performance

## Redis Usage

### Activity Tracking
```python
# Track video view
tracker.track_video_view(user_id, video_id, video_url, position, feed_type, session_id)

# Track feed request
tracker.track_feed_request(user_id, endpoint, params, session_id)

# Flush to MySQL
tracker.flush_user_activity_to_mysql(user_id)
```

### Auto-Flush Triggers
1. 50+ accumulated activities for a user
2. Every 15 minutes (background task)
3. Manual flush on endpoint call

## Logging

### Logger Setup
```python
from utils.logger import LoggerConfig

logger = LoggerConfig.get_logger(__name__)

# Log levels
logger.info("Informational message")
logger.warning("Warning message")
logger.error("Error message")
logger.debug("Debug message")
```

### Log Format
- **Timezone**: GMT-5 (Colombia/Bogotá)
- **Format**: `%(asctime)s - %(name)s - %(levelname)s - %(message)s`
- **File**: `logs/talent.log`
- **Levels**: INFO for normal ops, ERROR for failures

## Performance

### Optimization Guidelines
1. **Pre-calculate scores** - Don't compute on-the-fly
2. **Use vectorized operations** - Pandas/NumPy for batch processing
3. **Cache lookups** - Dictionary mapping for O(1) access
4. **Batch operations** - Process multiple items at once
5. **Limit DataFrame copies** - Use `.copy()` only when necessary

### Response Time Targets
- Feed generation: < 0.2s
- Data reload: ~30-40s
- API endpoint response: < 0.3s

## Data Processing

### Pandas Usage
```python
# Select and filter
candidatos = self.videos_df[
    (~self.videos_df['id'].isin(ids_excluir)) &
    (self.videos_df['pasa_gate_calidad'] == 1)
].copy()

# Vectorized operations
candidatos['score'] = (
    candidatos['views'] * 0.4 +
    candidatos['rating'] * 0.3 +
    candidatos['score_temporal'] * 0.3
)

# Sample with weights
indices = np.random.choice(len(df), size=n, p=weights, replace=False)
```

### DataFrame Management
```python
# Always use .copy() when modifying
df_subset = df[condition].copy()

# Prefer iloc for single-row access
row_data = df.iloc[0]

# Use iterrows sparingly (slow)
for idx, row in df.iterrows():
    # process
```

## Security

### SSH Tunnel Setup
```python
tunnel = SSHTunnelForwarder(
    (ssh_host, 22),
    ssh_username=ssh_user,
    ssh_pkey=str(ssh_key_path),
    remote_bind_address=(target_host, target_port),
    local_bind_address=('127.0.0.1', 0)
)
tunnel.start()
```

### Credentials Management
- Never commit `.env` or `.pem` files
- Use relative paths from project root
- Load from `credentials/` directory
- Set strict permissions on SSH keys (600 or 400)

## Docker

### Container Configuration
- **Base**: `python:3.13-alpine3.22`
- **Workers**: 4 (gunicorn)
- **Timeout**: 120s
- **Port**: 5002
- **Platform**: `linux/amd64` for production

### Volumes
```yaml
volumes:
  - ./credentials:/app/credentials:ro
  - ./data:/app/data:ro
  - ./logs:/app/logs
```

## Testing

### Query Testing
```python
# Use connection context manager
with MySQLConnection() as conn:
    results = conn.execute_query(query, params)
```

### Redis Testing
```python
# Use Redis connection
with RedisConnection() as redis:
    redis_client = redis.connection
    # Test operations
```

## Git Workflow

### Commit Messages
Use Conventional Commits in English:
- `feat:` - New feature
- `fix:` - Bug fix
- `refactor:` - Code restructuring
- `docs:` - Documentation
- `perf:` - Performance improvement
- `test:` - Tests
- `chore:` - Maintenance

Example:
```bash
feat: add contextual bandits with LinUCB algorithm
fix: resolve Redis connection timeout issues
refactor: optimize DataFrame operations in recommendation engine
```

### Files to Ignore
- `credentials/.env`
- `credentials/*.pem`
- `logs/`
- `__pycache__/`
- `.dockerignore`

## Error Handling

### Best Practices
```python
try:
    result = risky_operation()
    logger.info(f"Operation successful: {result}")
    return result
except SpecificException as e:
    logger.error(f"Specific error: {e}")
    # Handle specific case
except Exception as e:
    logger.error(f"Unexpected error: {e}")
    # Fallback behavior
    raise
```

### Graceful Degradation
- Return empty results instead of errors
- Log errors but continue operation
- Provide default values when data is missing

## Data Structures

### Video/Resume Object
```python
{
    "type": "resume",
    "id": int,
    "name": str,
    "slug": str,
    "description": str,
    "video": str,  # URL
    "image": str,  # URL
    "user_id": int,
    "user_name": str,
    # ... more fields
}
```

### Challenge/Flow Object
```python
{
    "type": "challenge",
    "id": int,
    "name": str,
    "description": str,
    "video_url": str,
    "interest_areas": list,
    "type_objectives": list,
    # ... more fields
}
```

## Recommendations

### Bandit Configuration
- **VMP**: alpha=1.5, beta=0.8 (exploitation)
- **AU**: alpha=1.8, beta=1.0 (balanced)
- **NU**: alpha=2.5, beta=1.3 (exploration)

### Features (18 total)
1. Score engagement
2. Score temporal
3. Score calidad
4. Score popularidad
5. Diversidad skills
6. Similitud skills
7. Match extendido
8. Coincidencia ciudad
9. Señal social
10-18. Additional features...

### Feed Metrics
- **Target diversity**: 100% creator diversity
- **Target skill diversity**: 60-75%
- **Catalog coverage**: 27-28%
- **New content ratio**: 25-35%

## When Making Changes

### Adding New Endpoint
1. Add endpoint in `api/endpoints.py`
2. Implement business logic in service layer
3. Add tracking for user activities
4. Update README.md documentation
5. Test with sample JSON output

### Modifying Recommendation Algorithm
1. Update bandit parameters in `services/recommendation.py`
2. Adjust pool sizes and selection criteria
3. Re-calculate advanced scores
4. Test with different user profiles
5. Monitor execution time

### Changing Data Loading
1. Update queries in `services/data_service.py`
2. Maintain backward compatibility
3. Consider data size and memory usage
4. Test with production dataset
5. Update `core/database.py` if needed

### Security Updates
1. Never expose credentials in logs
2. Use environment variables for sensitive data
3. Validate user inputs
4. Implement rate limiting if needed
5. Update SSH keys periodically

## Common Tasks

### Reload Data Without Restart
```bash
curl -X POST http://localhost:5002/api/search/reload
```

### View Logs
```bash
# Docker logs
docker logs source

# Application logs
cat logs/talent.log
```

### Build and Deploy
```bash
# Build image
docker build -t talentpitch-search:latest .

# Run container
docker run -d --name source \
  -p 5002:5002 \
  -v $(pwd)/credentials:/app/credentials:ro \
  -v $(pwd)/data:/app/data \
  -v $(pwd)/logs:/app/logs \
  -e ENVIRONMENT=production \
  talentpitch-search:latest
```

## Important Notes

1. **Always** use singleton pattern for core services
2. **Always** use connection context managers (with statements)
3. **Always** log operations at appropriate levels
4. **Always** handle missing data gracefully
5. **Always** close connections when done
6. **Never** commit credentials or keys
7. **Never** hardcode credentials
8. **Never** expose sensitive data in logs
9. **Never** modify DataFrames without .copy()
10. **Never** commit logs or cache files
