# Human notes

This application is part of Aia, our automated trading assistante decentralized system. We do not request any help for now.

This application, running on ```localhost:app_port``` will display any number of instruments received from a redis stream running on ```redis_port``` with the pattern ```redis_key_pattern```, from the file ```config/main.json```

```json
{
  "redis_key_pattern": "price_data:*:*",
  "app_port": 8051,
  "redis_port": 6379
}
```





