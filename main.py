import discord
from discord import app_commands
from discord.ext import commands
import os
from dotenv import load_dotenv

# --- Config ---
load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")
if not TOKEN:
    raise SystemExit("Error: DISCORD_TOKEN not set. Add it to your .env file.")

# --- Bot setup ---
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)
tree = bot.tree

# --- Helper ---
def has_permission(member: discord.Member) -> bool:
    """Check if the member has Manage Messages permission."""
    return member.guild_permissions.manage_messages

async def silent(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)
    await interaction.delete_original_response()

# --- On ready ---
@bot.event
async def on_ready():
    print(f"✅ Logged in as {bot.user}")

# --- Manual sync (owner only, avoids rate limits) ---
@bot.command()
@commands.is_owner()
async def sync(ctx):
    synced = await tree.sync()
    await ctx.send(f"✅ Synced {len(synced)} commands.")

# ============================================================
# SLASH COMMANDS
# ============================================================

# --- /say (inline for single line, modal for multiline) ---
@tree.command(name="say", description="Send a message as Sumi Bot in this channel")
@app_commands.describe(
    message="Message to send (leave empty to open multiline editor)",
    image="Image to attach to the message"
)
async def say(interaction: discord.Interaction, message: str = None, image: discord.Attachment = None):
    if not has_permission(interaction.user):
        await interaction.response.send_message("❌ You need Manage Messages permission.", ephemeral=True)
        return

    # If message or image provided inline, send directly
    if message or image:
        file = await image.to_file() if image else None
        await interaction.channel.send(content=message, file=file)
        await silent(interaction)
        return

    # Otherwise open modal for multiline (modals cannot include file uploads)
    channel = interaction.channel

    class SayModal(discord.ui.Modal, title="Send Message as Bot"):
        message_input = discord.ui.TextInput(
            label="Message",
            style=discord.TextStyle.paragraph,
            placeholder="Type your message here... (supports multiple lines)",
            required=True
        )

        async def on_submit(self, modal_interaction: discord.Interaction):
            await channel.send(self.message_input.value)
            await modal_interaction.response.send_message("_ _", ephemeral=True)
            await modal_interaction.delete_original_response()

    await interaction.response.send_modal(SayModal())

# --- /edit ---
@tree.command(name="edit", description="Edit a previous bot message in this channel")
@app_commands.describe(
    message_id="ID of the bot message to edit",
    new_content="New message content",
    image="New image to attach (replaces existing attachments)"
)
async def edit(interaction: discord.Interaction, message_id: str, new_content: str = None, image: discord.Attachment = None):
    if not has_permission(interaction.user):
        await interaction.response.send_message("❌ You need Manage Messages permission.", ephemeral=True)
        return
    if not new_content and not image:
        await interaction.response.send_message("❌ Provide new content, a new image, or both.", ephemeral=True)
        return
    try:
        target = await interaction.channel.fetch_message(int(message_id))
        if target.author != bot.user:
            await interaction.response.send_message("❌ I can only edit my own messages.", ephemeral=True)
            return
        kwargs = {}
        if new_content is not None:
            kwargs["content"] = new_content
        if image:
            kwargs["attachments"] = [await image.to_file()]
        await target.edit(**kwargs)
        await silent(interaction)
    except ValueError:
        await interaction.response.send_message("❌ Invalid message ID.", ephemeral=True)
    except discord.NotFound:
        await interaction.response.send_message("❌ Message not found.", ephemeral=True)

# --- /delete ---
@tree.command(name="delete", description="Delete a bot message in this channel")
@app_commands.describe(message_id="ID of the bot message to delete")
async def delete(interaction: discord.Interaction, message_id: str):
    if not has_permission(interaction.user):
        await interaction.response.send_message("❌ You need Manage Messages permission.", ephemeral=True)
        return
    try:
        target = await interaction.channel.fetch_message(int(message_id))
        if target.author != bot.user:
            await interaction.response.send_message("❌ I can only delete my own messages.", ephemeral=True)
            return
        await target.delete()
        await silent(interaction)
    except ValueError:
        await interaction.response.send_message("❌ Invalid message ID.", ephemeral=True)
    except discord.NotFound:
        await interaction.response.send_message("❌ Message not found.", ephemeral=True)

# --- /reply (slash command with image support) ---
@tree.command(name="reply", description="Reply to a message as Sumi Bot")
@app_commands.describe(
    message_id="ID of the message to reply to",
    message="Text content of the reply",
    image="Image to attach to the reply"
)
async def reply(interaction: discord.Interaction, message_id: str, message: str = None, image: discord.Attachment = None):
    if not has_permission(interaction.user):
        await interaction.response.send_message("❌ You need Manage Messages permission.", ephemeral=True)
        return
    if not message and not image:
        await interaction.response.send_message("❌ Provide a message, an image, or both.", ephemeral=True)
        return
    try:
        target = await interaction.channel.fetch_message(int(message_id))
        file = await image.to_file() if image else None
        await target.reply(content=message, file=file)
        await silent(interaction)
    except ValueError:
        await interaction.response.send_message("❌ Invalid message ID.", ephemeral=True)
    except discord.NotFound:
        await interaction.response.send_message("❌ Message not found.", ephemeral=True)

# ============================================================
# CONTEXT MENU COMMANDS (right-click a message)
# ============================================================

# --- Right-click → Reply as Bot ---
@tree.context_menu(name="Reply as Sumi Bot")
async def context_reply(interaction: discord.Interaction, message: discord.Message):
    if not has_permission(interaction.user):
        await interaction.response.send_message("❌ You don't have permission.", ephemeral=True)
        return

    class ReplyModal(discord.ui.Modal, title="Reply as Bot"):
        reply_text = discord.ui.TextInput(
            label="Your reply",
            style=discord.TextStyle.paragraph,
            placeholder="Type your reply here...",
            required=True
        )

        async def on_submit(self, modal_interaction: discord.Interaction):
            await message.reply(self.reply_text.value)
            await modal_interaction.response.send_message("_ _", ephemeral=True)
            await modal_interaction.delete_original_response()

    await interaction.response.send_modal(ReplyModal())

# --- Right-click → Edit as Bot ---
@tree.context_menu(name="Edit Sumi Bot message")
async def context_edit(interaction: discord.Interaction, message: discord.Message):
    if not has_permission(interaction.user):
        await interaction.response.send_message("❌ You don't have permission.", ephemeral=True)
        return
    if message.author != bot.user:
        await interaction.response.send_message("❌ I can only edit my own messages.", ephemeral=True)
        return

    class EditModal(discord.ui.Modal, title="Edit Bot Message"):
        new_content = discord.ui.TextInput(
            label="New content",
            style=discord.TextStyle.paragraph,
            default=message.content,
            required=True
        )

        async def on_submit(self, modal_interaction: discord.Interaction):
            await message.edit(content=self.new_content.value)
            await modal_interaction.response.send_message("_ _", ephemeral=True)
            await modal_interaction.delete_original_response()

    await interaction.response.send_modal(EditModal())

# --- Right-click → Delete as Bot ---
@tree.context_menu(name="Delete Sumi Bot message")
async def context_delete(interaction: discord.Interaction, message: discord.Message):
    if not has_permission(interaction.user):
        await interaction.response.send_message("❌ You don't have permission.", ephemeral=True)
        return
    if message.author != bot.user:
        await interaction.response.send_message("❌ I can only delete my own messages.", ephemeral=True)
        return
    await message.delete()
    await silent(interaction)

# --- Run ---
bot.run(TOKEN)