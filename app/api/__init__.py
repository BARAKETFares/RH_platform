"""
Package API REST.

Architecture :
    /api/v1/   → Blueprint api_v1  (version stable)
    /api/v2/   → Blueprint api_v2  (future version)

Toutes les routes API :
  - Retournent du JSON (Content-Type: application/json)
  - Utilisent JWT (stateless, pas de session Flask)
  - Sont exemptées de CSRF (géré dans create_app)
  - Respectent les conventions REST (verbes HTTP, codes de statut)
"""
