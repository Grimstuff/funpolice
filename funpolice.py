import discord # type: ignore
from discord import app_commands # type: ignore
from discord.ext import commands # type: ignore
import re
import json
import os
from discord.ui import Button, View # type: ignore

# Load secrets
with open('secrets.json', 'r') as f:
    secrets = json.load(f)
    BOT_TOKEN = secrets['BOT_TOKEN']

# Function to load config
def load_config():
    with open('config.json', 'r') as f:
        config = json.load(f)
    forbidden = {}
    for replacement, words in config.items():
        if isinstance(words, str):
            forbidden[words.lower()] = replacement
        elif isinstance(words, list):
            for word in words:
                forbidden[word.lower()] = replacement
    return config, forbidden

# Initial config load
config, forbidden = load_config()

# Compile regex pattern - includes optional 's' at the end for plurals
def update_pattern():
    # We need a more specific pattern to properly handle plurals for case-insensitivity
    # Create a pattern that will match both singular and plural forms explicitly
    pattern_parts = []
    for word in forbidden.keys():
        pattern_parts.append(re.escape(word))  # Original word
        pattern_parts.append(re.escape(word) + r's')  # Plural form
    
    return r'\b(' + '|'.join(pattern_parts) + r')\b'

pattern = update_pattern()

# Function to handle pluralization of replacements
def pluralize_replacement(match, replacement):
    # Simple English pluralization for the replacement
    # We've already determined this needs pluralization before calling
    if replacement.endswith('y'):
        return replacement[:-1] + 'ies'  # city -> cities
    elif replacement.endswith('sh') or replacement.endswith('ch') or replacement.endswith('x'):
        return replacement + 'es'  # bush -> bushes, church -> churches, box -> boxes
    else:
        return replacement + 's'  # cat -> cats

# Set up the bot with intents
intents = discord.Intents.default()
intents.message_content = True
# Using a non-standard prefix to avoid conflicts with other bots
# We'll only use slash commands, but need to set a prefix for the Bot class
bot = commands.Bot(command_prefix='__funpolice__', intents=intents, help_command=None)

# Adding an event handler to suppress command not found errors
@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.CommandNotFound):
        # Silently ignore command not found errors
        return
    # For other errors, print them to console
    print(f"Command error: {error}")

# Function to get or create a webhook
async def get_webhook(channel):
    try:
        webhooks = await channel.webhooks()
        for wh in webhooks:
            if wh.name == "WordFilterWebhook":
                return wh
        return await channel.create_webhook(name="WordFilterWebhook")
    except discord.Forbidden:
        print(f"Cannot create webhook in {channel.name}. Ensure bot has 'Manage Webhooks' permission.")
        return None

# Function to get the appropriate avatar URL (guild-specific if available)
def get_avatar_url(user, guild):
    """
    Get the guild-specific avatar URL for a user if available, otherwise fall back to global avatar.
    
    Args:
        user: The discord.User or discord.Member object
        guild: The discord.Guild object
    
    Returns:
        str: URL of the user's avatar (guild-specific if available)
    """
    # Make sure we have valid objects
    if user is None or guild is None:
        return None
    
    # If the user is already a member object with the right guild
    if hasattr(user, 'guild') and user.guild.id == guild.id and user.guild_avatar:
        return user.guild_avatar.url
    
    # Otherwise, try to get the member object from the guild
    try:
        member = guild.get_member(user.id)
        if member and member.guild_avatar:
            return member.guild_avatar.url
    except:
        pass
    
    # Fall back to global avatar
    if hasattr(user, 'avatar') and user.avatar:
        return user.avatar.url
    
    # Last resort: default avatar
    return user.default_avatar.url if hasattr(user, 'default_avatar') else None

# Event handler for new messages
@bot.event
async def on_message(message):
    if message.author.bot:
        return
    
    original_content = message.content
    match_content = original_content
    nospace_content = re.sub(r'\s+', '', original_content)  # Remove spaces for terms like "n i g g e r"
    
    # First check if there are words with spaces between letters
    space_matches = re.findall(pattern, nospace_content, flags=re.IGNORECASE)
    
    # If we found matches in the no-space version but not in the original,
    # it means there are words with spaces between letters
    if space_matches:
        # We need to replace the spaced version in the original content
        for match in space_matches:
            # Check if this is a plural form directly
            is_plural = match.lower().endswith('s')
            
            # Get base form by removing 's' if it's a plural and its base exists in forbidden
            base_match = match[:-1] if is_plural and match[:-1].lower() in forbidden else match
            
            # Get the appropriate replacement
            if base_match.lower() in forbidden:
                replacement = forbidden.get(base_match.lower())
            elif match.lower() in forbidden:  # Direct match including plural forms
                replacement = forbidden.get(match.lower())
            else:
                # Skip if we can't find a replacement
                continue
            
            # Handle pluralization if needed
            if is_plural and not match.lower() in forbidden:
                replacement = pluralize_replacement(match, replacement)
            
            # Determine capitalization of the original match
            if match.isupper():
                replacement = replacement.upper()
            elif match[0].isupper():
                replacement = replacement[0].upper() + replacement[1:]
            
            # Find the spaced version in the original content - this is tricky
            # We'll use a regex that allows for spaces between characters
            spaced_pattern = ''.join([c + r'\s*' for c in base_match[:-1]]) + base_match[-1]
            if is_plural:
                spaced_pattern += r'\s*s'
            
            # Replace in the original content - make sure to use re.IGNORECASE
            match_content = re.sub(spaced_pattern, replacement, match_content, flags=re.IGNORECASE)
    
    # Now process regular matches - preserve case using a function
    def replace_word(m):
        match = m.group(0)
        # Get the base form (without trailing 's' if it exists)
        base_match = match[:-1] if match.endswith('s') and match[:-1].lower() in forbidden else match
        replacement = forbidden.get(base_match.lower(), base_match)
        
        # Handle pluralization
        if match.endswith('s') and match[:-1].lower() in forbidden:
            replacement = pluralize_replacement(match, replacement)
            
        # Preserve capitalization of the original word for better natural appearance
        if match.isupper():
            return replacement.upper()
        elif match[0].isupper():
            return replacement[0].upper() + replacement[1:]
        return replacement
    
    new_content = re.sub(pattern, replace_word, match_content, flags=re.IGNORECASE)
    
    if new_content != original_content:
        try:
            await message.delete()
        except discord.Forbidden:
            print(f"Cannot delete message in {message.channel.name}. Ensure bot has 'Manage Messages' permission.")
            return
        except discord.NotFound:
            print(f"Message {message.id} already deleted. Continuing with filter process.")
            # Continue with the filter process even if the message is already deleted
        
        webhook = await get_webhook(message.channel)
        if webhook:
            # Get the appropriate avatar URL (guild-specific if available)
            avatar_url = get_avatar_url(message.author, message.guild)
            
            # If we couldn't get any avatar URL (unlikely but possible), use a default
            if avatar_url is None:
                # Discord's default avatar as a last resort
                avatar_url = message.author.default_avatar.url if hasattr(message.author, 'default_avatar') else None
            
            # Check if the message is a reply
            if message.reference and message.reference.message_id:
                try:
                    # Try to fetch the message being replied to
                    replied_msg = await message.channel.fetch_message(message.reference.message_id)
                    
                    # Format for replied content - truncate if too long
                    replied_content = replied_msg.content
                    if not replied_content:  # Check if the message has no text content
                        replied_content = "*[message had no text content]*"
                    
                    if len(replied_content) > 100:
                        replied_content = replied_content[:100] + "..."
                    
                    # Always use mention for the replied user, regardless of whether they're a bot or not
                    quoted_text = f"> {replied_msg.author.mention}: {replied_content}"
                    
                    # Combine quote with the filtered message
                    combined_content = f"{quoted_text}\n{new_content}"
                    
                    # Ensure the mention works by explicitly allowing it
                    await webhook.send(
                        content=combined_content,
                        username=message.author.display_name,
                        avatar_url=avatar_url,
                        allowed_mentions=discord.AllowedMentions(
                            users=[replied_msg.author],  # Explicitly allow mentioning the replied user
                            everyone=False,
                            roles=False
                        )
                    )
                except discord.NotFound:
                    # If we can't find the replied message, just send the filtered message
                    await webhook.send(
                        content=new_content,
                        username=message.author.display_name,
                        avatar_url=avatar_url,
                        allowed_mentions=discord.AllowedMentions(everyone=False, roles=False)
                    )
            else:
                # Not a reply, just send the filtered message
                await webhook.send(
                    content=new_content,
                    username=message.author.display_name,
                    avatar_url=avatar_url,
                    allowed_mentions=discord.AllowedMentions(everyone=False, roles=False)
                )

# Admin-only check for slash commands
def is_admin():
    async def predicate(interaction: discord.Interaction) -> bool:
        if not interaction.user.guild_permissions.administrator:
            raise app_commands.CheckFailure("You need administrator permissions to use this command.")
        return True
    return app_commands.check(predicate)

# Autocomplete function for replacement parameter
async def replacement_autocomplete(interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
    replacements = list(config.keys())
    filtered = [r for r in replacements if current.lower() in r.lower()]
    return [app_commands.Choice(name=r, value=r) for r in filtered[:25]]

# View class for pagination buttons
class PaginationView(View):
    def __init__(self, user_id: int, pages: list[discord.Embed], current_page: int = 0):
        super().__init__(timeout=300)  # 5-minute timeout
        self.user_id = user_id
        self.pages = pages
        self.current_page = current_page
        self.update_buttons()

    def update_buttons(self):
        self.clear_items()
        # Previous button
        prev_button = Button(label="Previous", style=discord.ButtonStyle.gray, disabled=self.current_page == 0)
        prev_button.callback = self.previous_page
        self.add_item(prev_button)
        # Next button
        next_button = Button(label="Next", style=discord.ButtonStyle.gray, disabled=self.current_page == len(self.pages) - 1)
        next_button.callback = self.next_page
        self.add_item(next_button)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        # Only the command issuer can use the buttons
        return interaction.user.id == self.user_id

    async def previous_page(self, interaction: discord.Interaction):
        self.current_page -= 1
        self.update_buttons()
        await interaction.response.edit_message(embed=self.pages[self.current_page], view=self)

    async def next_page(self, interaction: discord.Interaction):
        self.current_page += 1
        self.update_buttons()
        await interaction.response.edit_message(embed=self.pages[self.current_page], view=self)

# Slash command to add multiple words to the filter
@app_commands.command(
    name="addfilter",
    description="Add one or more words to the filter (admin only)."
)
@is_admin()
@app_commands.autocomplete(replacement=replacement_autocomplete)
async def add_filter(
    interaction: discord.Interaction,
    replacement: str,
    words: str
):
    """Add multiple words to the filter under a replacement phrase.
    Separate words with commas."""
    global config, forbidden, pattern
    
    # Normalize inputs
    replacement = replacement.strip()
    # Split by commas and remove whitespace from each word
    word_list = [word.lower().strip() for word in words.split(',') if word.strip()]
    
    if not word_list:
        await interaction.response.send_message("No valid words provided.", ephemeral=True)
        return
    
    # Keep track of added words
    added_words = []
    already_filtered = []
    
    # Update config
    if replacement in config:
        if isinstance(config[replacement], list):
            for word in word_list:
                if word not in config[replacement]:
                    config[replacement].append(word)
                    added_words.append(word)
                else:
                    already_filtered.append(word)
        else:
            # Convert single value to list and add new words
            existing_word = config[replacement]
            config[replacement] = [existing_word]
            for word in word_list:
                if word != existing_word:
                    config[replacement].append(word)
                    added_words.append(word)
                else:
                    already_filtered.append(word)
    else:
        config[replacement] = word_list
        added_words = word_list
    
    # Save config
    with open('config.json', 'w') as f:
        json.dump(config, f, indent=4)
    
    # Reload forbidden and pattern
    config, forbidden = load_config()
    pattern = update_pattern()
    
    # Prepare response message
    response = []
    if added_words:
        response.append(f"Added {len(added_words)} word(s) to filter with replacement '{replacement}':")
        response.append(", ".join(f"'{word}'" for word in added_words))
    
    if already_filtered:
        words_with_quotes = [f"'{word}'" for word in already_filtered]
        response.append(f"These words were already in the filter: {', '.join(words_with_quotes)}")
    
    await interaction.response.send_message("\n".join(response), ephemeral=True)

# Slash command to remove a word from the filter
@app_commands.command(
    name="deletefilter",
    description="Remove a specific word from the filter (admin only)."
)
@is_admin()
async def delete_filter(
    interaction: discord.Interaction,
    word: str
):
    """Remove a specific word from the filter."""
    global config, forbidden, pattern
    
    word = word.lower().strip()
    found = False
    
    # Search for the word in config
    for replacement, words in list(config.items()):
        if isinstance(words, list) and word in words:
            config[replacement].remove(word)
            if not config[replacement]:  # Remove empty lists
                del config[replacement]
            found = True
            break
        elif isinstance(words, str) and words.lower() == word:
            del config[replacement]
            found = True
            break
    
    if not found:
        await interaction.response.send_message(f"Word '{word}' not found in the filter.", ephemeral=True)
        return
    
    # Save config
    with open('config.json', 'w') as f:
        json.dump(config, f, indent=4)
    
    # Reload forbidden and pattern
    config, forbidden = load_config()
    pattern = update_pattern()
    
    await interaction.response.send_message(f"Removed word '{word}' from the filter.", ephemeral=True)

# Command to delete an entire replacement category
@app_commands.command(
    name="deletereplacement",
    description="Delete an entire replacement category and all associated words (admin only)."
)
@is_admin()
@app_commands.autocomplete(replacement=replacement_autocomplete)
async def delete_replacement(
    interaction: discord.Interaction,
    replacement: str
):
    """Delete an entire replacement category and all associated words."""
    global config, forbidden, pattern
    
    replacement = replacement.strip()
    
    if replacement not in config:
        await interaction.response.send_message(f"Replacement category '{replacement}' not found.", ephemeral=True)
        return
    
    # Get the words for confirmation message
    words = config[replacement]
    word_count = 1 if isinstance(words, str) else len(words)
    words_str = words if isinstance(words, str) else ", ".join(words)
    
    # Create a warning message with confirmation button
    warning_message = (
        f"⚠️ **WARNING** ⚠️\n\n"
        f"You are about to delete the replacement category '{replacement}' and ALL {word_count} associated word(s):\n"
        f"```{words_str}```\n"
        f"This action cannot be undone. Please confirm or cancel:"
    )
    
    # Create confirmation view
    view = ConfirmationView(user_id=interaction.user.id)
    await interaction.response.send_message(warning_message, view=view, ephemeral=True)
    
    # Wait for interaction
    await view.wait()
    
    # Check if confirmed
    if not view.confirmed:
        return  # User canceled or timed out
    
    # Delete the category
    del config[replacement]
    
    # Save config
    with open('config.json', 'w') as f:
        json.dump(config, f, indent=4)
    
    # Reload forbidden and pattern
    config, forbidden = load_config()
    pattern = update_pattern()
    
    # Send follow-up message confirming deletion
    await interaction.followup.send(
        f"Successfully deleted replacement category '{replacement}' with {word_count} word(s).", 
        ephemeral=True
    )

# Slash command to reload the config
@app_commands.command(
    name="reloadconfig",
    description="Reload the config file (admin only)."
)
@is_admin()
async def reload_config(interaction: discord.Interaction):
    """Reload the config.json file."""
    global config, forbidden, pattern
    
    try:
        config, forbidden = load_config()
        pattern = update_pattern()
        await interaction.response.send_message("Config file reloaded successfully.", ephemeral=True)
    except Exception as e:
        await interaction.response.send_message(f"Failed to reload config: {str(e)}", ephemeral=True)

# Slash command to list filters
@app_commands.command(
    name="listfilters",
    description="List all word filters (admin only)."
)
@is_admin()
async def list_filters(interaction: discord.Interaction):
    """List all word filters in a paginated embed."""
    if not config:
        await interaction.response.send_message("No filters found in config.", ephemeral=True)
        return
    
    # Create pages (5 categories per page)
    items_per_page = 5
    replacements = list(config.items())
    pages = []
    
    for i in range(0, len(replacements), items_per_page):
        embed = discord.Embed(title="Word Filters", color=0x00ff00)
        embed.set_footer(text=f"Page {i // items_per_page + 1} of {len(replacements) // items_per_page + 1}")
        for replacement, words in replacements[i:i + items_per_page]:
            # Convert words to string if it's a single string
            words_str = ", ".join(words) if isinstance(words, list) else words
            embed.add_field(name=replacement, value=words_str, inline=False)
        pages.append(embed)
    
    # Send the first page with navigation buttons
    view = PaginationView(user_id=interaction.user.id, pages=pages)
    await interaction.response.send_message(embed=pages[0], view=view, ephemeral=True)

# Sync commands on bot startup
@bot.event
async def on_ready():
    print(f"Logged in as {bot.user}")
    try:
        synced = await bot.tree.sync()
        print(f"Synced {len(synced)} command(s)")
    except Exception as e:
        print(f"Failed to sync commands: {e}")

# Create a confirmation button view for deletion
class ConfirmationView(View):
    def __init__(self, user_id: int):
        super().__init__(timeout=60)  # 60-second timeout
        self.user_id = user_id
        self.confirmed = False

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        # Only the command issuer can use the buttons
        return interaction.user.id == self.user_id

    @discord.ui.button(label="Confirm Deletion", style=discord.ButtonStyle.danger)
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.confirmed = True
        self.stop()
        await interaction.response.edit_message(content="Deletion confirmed!", view=None)

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.stop()
        await interaction.response.edit_message(content="Deletion canceled.", view=None)

# Error handler for slash command checks
@bot.tree.error
async def on_app_command_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    if isinstance(error, app_commands.CheckFailure):
        await interaction.response.send_message("You need administrator permissions to use this command.", ephemeral=True)
    else:
        # Log the error instead of raising it
        print(f"Error in slash command: {error}")
        await interaction.response.send_message("An error occurred while executing the command.", ephemeral=True)

# Add commands to the bot's command tree
bot.tree.add_command(add_filter)
bot.tree.add_command(delete_filter)
bot.tree.add_command(delete_replacement)
bot.tree.add_command(reload_config)
bot.tree.add_command(list_filters)

# Run the bot
bot.run(BOT_TOKEN)