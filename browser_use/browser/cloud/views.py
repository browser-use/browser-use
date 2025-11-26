from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

ProxyCountryCode = (
	Literal[
		'us',  # United States
		'uk',  # United Kingdom
		'fr',  # France
		'it',  # Italy
		'jp',  # Japan
		'au',  # Australia
		'de',  # Germany
		'fi',  # Finland
		'ca',  # Canada
		'in',  # India
	]
	| str
)

# Browser session timeout limits (in minutes)
MAX_FREE_USER_SESSION_TIMEOUT = 15  # Free users limited to 15 minutes
MAX_PAID_USER_SESSION_TIMEOUT = 240  # Paid users can go up to 4 hours


# Requests
class CreateBrowserRequest(BaseModel):
	"""Request to create a cloud browser instance.

	Args:
	    cloud_profile_id: The ID of the profile to use for the session
	    cloud_proxy_country_code: Country code for proxy location
	    cloud_timeout: The timeout for the session in minutes
	"""

	model_config = ConfigDict(extra='forbid', populate_by_name=True)

	profile_id: UUID | str | None = Field(
		default=None,
		alias='cloud_profile_id',
		description='The ID of the profile to use for the session. Can be a UUID or a string of UUID.',
		title='Cloud Profile ID',
	)

	proxy_country_code: ProxyCountryCode | None = Field(
		default=None,
		alias='cloud_proxy_country_code',
		description='Country code for proxy location.',
		title='Cloud Proxy Country Code',
	)

	timeout: int | None = Field(
		ge=1,
		le=MAX_PAID_USER_SESSION_TIMEOUT,
		default=None,
		alias='cloud_timeout',
		description=f'The timeout for the session in minutes. Free users are limited to {MAX_FREE_USER_SESSION_TIMEOUT} minutes, paid users can use up to {MAX_PAID_USER_SESSION_TIMEOUT} minutes ({MAX_PAID_USER_SESSION_TIMEOUT // 60} hours).',
		title='Cloud Timeout',
	)


CloudBrowserParams = CreateBrowserRequest  # alias for easier readability


# Responses
class CloudBrowserResponse(BaseModel):
	"""Response from cloud browser API."""

	id: str
	status: str
	liveUrl: str = Field(alias='liveUrl')
	cdpUrl: str = Field(alias='cdpUrl')
	timeoutAt: str = Field(alias='timeoutAt')
	startedAt: str = Field(alias='startedAt')
	finishedAt: str | None = Field(alias='finishedAt', default=None)


# Errors
class CloudBrowserError(Exception):
	"""Exception raised when cloud browser operations fail."""

	pass


class CloudBrowserAuthError(CloudBrowserError):
	"""Exception raised when cloud browser authentication fails."""

	pass
