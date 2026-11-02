# Copyright 2026 MSPbots.ai
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
"""Process settings. Holds no credentials: those arrive per request as headers."""

from pydantic_settings import BaseSettings, SettingsConfigDict

# Gorelo publishes two entirely separate regional hosts, each with its own
# Swagger document (help.gorelo.io/api-overview, fetched 2026-11-02). There is
# no single global entry point, so the caller must say which one applies.
REGION_HOSTS = {
    "us": "https://api.usw.gorelo.io",
    "au": "https://api.aue.gorelo.io",
}
MAX_PAGE_SIZE = 200
DEFAULT_PAGE_SIZE = 50


class Settings(BaseSettings):
    # extra="ignore": the runtime injects variables this project does not declare.
    model_config = SettingsConfigDict(extra="ignore")

    mcp_http_port: int = 8080
    mcp_http_host: str = "0.0.0.0"
    log_level: str = "INFO"


def get_settings() -> Settings:
    return Settings()
