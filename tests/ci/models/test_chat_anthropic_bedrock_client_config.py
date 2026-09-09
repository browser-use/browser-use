from browser_use.llm.aws.chat_anthropic import ChatAnthropicBedrock


def test_get_client_preserves_zero_max_retries() -> None:
	llm = ChatAnthropicBedrock(
		aws_access_key='test-access-key',
		aws_secret_key='test-secret-key',
		aws_region='us-east-1',
		max_retries=0,
	)

	client = llm.get_client()

	assert client.max_retries == 0
