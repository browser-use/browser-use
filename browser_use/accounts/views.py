"""Account data models for user credential management."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, ConfigDict, Field
from uuid_extensions import uuid7str


# Well-known platform domain mappings for auto-detection
PLATFORM_DOMAINS: dict[str, list[str]] = {
	'github': ['github.com', '*.github.com'],
	'google': ['google.com', 'accounts.google.com', '*.google.com'],
	'amazon': ['amazon.com', 'amazon.co.jp', 'amazon.co.uk', '*.amazon.com'],
	'taobao': ['taobao.com', 'login.taobao.com', '*.taobao.com'],
	'jd': ['jd.com', 'passport.jd.com', '*.jd.com'],
	'tmall': ['tmall.com', 'login.tmall.com', '*.tmall.com'],
	'twitter': ['twitter.com', 'x.com', '*.twitter.com', '*.x.com'],
	'facebook': ['facebook.com', '*.facebook.com'],
	'linkedin': ['linkedin.com', '*.linkedin.com'],
	'reddit': ['reddit.com', '*.reddit.com'],
	'netflix': ['netflix.com', '*.netflix.com'],
	'spotify': ['spotify.com', 'accounts.spotify.com', '*.spotify.com'],
	'apple': ['apple.com', 'appleid.apple.com', '*.apple.com', '*.icloud.com'],
	'microsoft': ['microsoft.com', 'login.microsoftonline.com', '*.microsoft.com', '*.live.com'],
	'ebay': ['ebay.com', 'signin.ebay.com', '*.ebay.com'],
	'shopify': ['shopify.com', '*.myshopify.com'],
	'gitlab': ['gitlab.com', '*.gitlab.com'],
	'bitbucket': ['bitbucket.org', '*.bitbucket.org'],
	'douyin': ['douyin.com', '*.douyin.com'],
	'bilibili': ['bilibili.com', '*.bilibili.com'],
	'weibo': ['weibo.com', '*.weibo.com'],
	'zhihu': ['zhihu.com', '*.zhihu.com'],
	'pinduoduo': ['pinduoduo.com', '*.pinduoduo.com'],
}


class AccountCredentials(BaseModel):
	"""Credentials for a platform account."""

	model_config = ConfigDict(extra='allow')

	username: str | None = None
	password: str | None = None
	email: str | None = None
	phone: str | None = None
	token: str | None = None
	two_factor_secret: str | None = None


class Account(BaseModel):
	"""A single platform account entry."""

	model_config = ConfigDict(extra='forbid')

	id: str = Field(default_factory=uuid7str)
	label: str
	platform: str
	domains: list[str] = Field(default_factory=list)
	credentials: AccountCredentials = Field(default_factory=AccountCredentials)
	metadata: dict[str, Any] = Field(default_factory=dict)
	created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
	updated_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class AccountsData(BaseModel):
	"""Top-level accounts file schema."""

	model_config = ConfigDict(extra='forbid')

	version: int = 1
	accounts: list[Account] = Field(default_factory=list)
