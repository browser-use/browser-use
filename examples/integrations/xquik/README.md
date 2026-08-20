# Xquik Tweet Search Integration

Use Xquik as a read-only custom action for Browser Use agents. The action searches
public X (Twitter) posts and returns bounded JSON with source URLs. Browser Use can
then open ordinary web sources to verify, compare, or extend the results.

This avoids placing an API key in an agent task. The action sends the key only in
the HTTPS request header. It excludes unneeded response metadata from agent context.
It also labels tweet text as untrusted data and returns only validated X source URLs.

## Setup

1. Follow the repository's local setup instructions.
2. Create an API key in the [Xquik dashboard](https://dashboard.xquik.com/en/account?tab=api-keys).
3. Export the key for the example process:

   ```sh
   export XQUIK_API_KEY='replace-with-your-key'
   ```

## Run

From the repository root, run:

```sh
uv run examples/integrations/xquik/xquik_tweet_search.py
```

The example registers `search_public_x_tweets` next to the standard browser tools.
It searches tweets about browser automation, then asks the agent to compare those
posts with the Browser Use releases page.

Change the task in `main()` to use another keyword, phrase, account, Tweet ID,
X status URL, or advanced search query. The action accepts 1 to 20 results and
supports `Latest` and `Top` ordering. Pass `next_cursor` back as `cursor` to read
another bounded page.

The example performs public searches only. It does not publish posts or modify an
X account. See the [tweet search API](https://docs.xquik.com/api-reference/x/search-tweets)
for the current query and response contract.

Xquik is an independent third-party service. Not affiliated with X Corp. "Twitter"
and "X" are trademarks of X Corp.
