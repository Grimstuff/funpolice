Discord wordfilter that replaces words while appearing as much like origional poster as possible.

Run bat file to setup and run bot. Will need a Discord Application API Key.

REQUIRED PERMISSIONS:
- Send Messages (to send filtered replacement messages)
- Manage Messages (to delete original filtered messages)
- Manage Webhooks (to send messages as the original user)
- Use Slash Commands (for admin configuration commands)
- Read Message History (to fetch replied-to messages for context)
- View Channels (to see messages in channels where bot operates)
- Attach Files (for preserving attachments in filtered messages)

NOTE: The bot needs these permissions in every channel where you want word filtering to work.
