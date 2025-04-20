# Slack Integration

Steps to create and configure a Slack bot:

1. Create a Slack App:
    *   Go to the Slack API: https://api.slack.com/apps
    *   Click on "Create New App".
    *   Choose "From scratch" and give your app a name and select the workspace.
    *   Provide a name and description for your bot (these are required fields).
2. Configure the Bot:
    *   Navigate to the "OAuth & Permissions" tab on the left side of the screen.
    *   Under "Scopes", add the necessary bot token scopes (add these "chat:write", "channels:history", "im:history").
3. Enable Event Subscriptions:
    *   Navigate to the "Event Subscriptions" tab.
    *   Enable events and add the necessary bot events (add these "message.channels", "message.im").
    *   Add your request URL (you can use ngrok to expose your local server if needed). [See how to set up ngrok](#installing-and-starting-ngrok).
    *   **Note:** The URL provided by ngrok is ephemeral and will change each time ngrok is started. You will need to update the request URL in the bot's settings each time you restart ngrok. [See how to update the request URL](#updating-the-request-url-in-bots-settings).
4. Add the bot to your Slack workspace:
    *   Navigate to the "OAuth & Permissions" tab.
    *   Under "OAuth Tokens for Your Workspace", click on "Install App to Workspace".
    *   Follow the prompts to authorize the app and add it to your workspace.
5. Set up environment variables:
    *   Obtain the `SLACK_SIGNING_SECRET`:
        *   Go to the Slack API: https://api.slack.com/apps
        *   Select your app.
        *   Navigate to the "Basic Information" tab.
        *   Copy the "Signing Secret".
    *   Obtain the `SLACK_BOT_TOKEN`:
        *   Go to the Slack API: https://api.slack.com/apps
        *   Select your app.
        *   Navigate to the "OAuth & Permissions" tab.
        *   Copy the "Bot User OAuth Token".
    *   Create a `.env` file in the root directory of your project and add the following lines:
        ```env
        SLACK_SIGNING_SECRET=your-signing-secret
        SLACK_BOT_TOKEN=your-bot-token
        ```
6. Invite the bot to a channel:
    *   Use the `/invite @your-bot-name` command in the Slack channel where you want the bot to be active.
7. Run the code in `examples/slack_example.py` to start the bot with your bot token and signing secret.
8. Write e.g. "$bu what's the weather in Tokyo?" to start a browser-use task and get a response inside the Slack channel.

## Installing and Starting ngrok

To expose your local server to the internet, you can use ngrok. Follow these steps to install and start ngrok:

1. Download ngrok from the official website: https://ngrok.com/download
2. Create a free account and follow the official steps to install ngrok.
3. Start ngrok by running the following command in your terminal:
    ```sh
    ngrok http 3000
    ```
    Replace `3000` with the port number your local server is running on.

## Updating the Request URL in Bot's Settings

If you need to update the request URL (e.g., when the ngrok URL changes), follow these steps:

1. Go to the Slack API: https://api.slack.com/apps
2. Select your app.
3. Navigate to the "Event Subscriptions" tab.
4. Update the "Request URL" field with the new ngrok URL. The URL should be something like: `https://<ngrok-id>.ngrok-free.app/slack/events`
5. Save the changes.

## Installing Required Packages

To run this example, you need to install the following packages:

- `fastapi`
- `uvicorn`
- `slack_sdk`

You can install these packages using pip:

```sh
pip install fastapi uvicorn slack_sdk
