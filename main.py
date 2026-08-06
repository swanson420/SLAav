"""
Entry point. Boots the FastAPI app defined in artifact_19_api_layer_CORRECTED.py.
"""

import uvicorn
from artifact_19_api_layer_CORRECTED import app

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8080)
