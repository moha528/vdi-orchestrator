"""Schémas Pydantic."""
from typing import Optional
from pydantic import BaseModel, Field


class TemplateIn(BaseModel):
    template_vmid: int
    group_name: str = Field(min_length=1, max_length=255)
    display_name: str = Field(min_length=1, max_length=255)
    protocol: str = "rdp"
    port: int = 3389
    default_username: Optional[str] = None
    default_password: Optional[str] = None
    cores: int = 2
    memory: int = 2048
    max_clones: int = 5
    enabled: bool = True
    guacamole_groups: list[str] = []


class TemplateOut(TemplateIn):
    id: int


class CloneOut(BaseModel):
    id: int
    vmid: int
    template_id: Optional[int]
    clone_name: str
    username: str
    ip_address: Optional[str]
    guac_connection_id: Optional[int]
    status: str
    created_at: str
    connected_at: Optional[str]
    last_activity: Optional[str]
    template_name: Optional[str] = None
    guac_url: Optional[str] = None


class CloneRequest(BaseModel):
    template_id: int


class DestroyRequest(BaseModel):
    backup: bool = True
