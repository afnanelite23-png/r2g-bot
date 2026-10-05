import asyncio
from datetime import datetime, timezone, timedelta
import json
import os
import random
import re
from collections import defaultdict, deque
import discord
from discord.ext import commands, tasks
from flask import Flask

# --- Flask Server for Render/UptimeRobot 24/7 Uptime ---
app = Flask(__name__)


@app.route("/")
def home():
  return "Bot is alive and running!"


def run_flask():
  port = int(os.environ.get("PORT", 10000))
  app.run(host="0.0.0.0", port=port)


# --- Bot Setup ---
intents = discord.Intents.default()
intents.message_content = True
intents.members = True
intents.guilds = True

# Prefix set to ">"
bot = commands.Bot(command_prefix=">", intents=intents, help_command=None)

CONFIG_FILE = "config.json"


def load_data():
  if not os.path.exists(CONFIG_FILE):
    return {
        "guilds": {},
        "modstats": {},
        "warns": {},
        "appeal_cooldowns": {},
        "jail_info": {},
        "giveaways": {},
        "levels": {},
    }
  with open(CONFIG_FILE, "r") as f:
    data = json.load(f)
    if "guilds" not in data:
      data["guilds"] = {}
    if "warns" not in data:
      data["warns"] = {}
    if "appeal_cooldowns" not in data:
      data["appeal_cooldowns"] = {}
    if "jail_info" not in data:
      data["jail_info"] = {}
    if "giveaways" not in data:
      data["giveaways"] = {}
    if "modstats" not in data:
      data["modstats"] = {}
    if "levels" not in data:
      data["levels"] = {}
    return data


def save_data(data):
  with open(CONFIG_FILE, "w") as f:
    json.dump(data, f, indent=4)


def get_config(guild_id, key):
  data = load_data()
  g_id = str(guild_id)
  if g_id not in data["guilds"]:
    return None
  return data["guilds"][g_id].get(key)


def set_config(guild_id, key, value):
  data = load_data()
  g_id = str(guild_id)
  if g_id not in data["guilds"]:
    data["guilds"][g_id] = {}
  data["guilds"][g_id][key] = value
  save_data(data)


async def send_log(guild, embed):
  log_channel_id = get_config(guild.id, "log_channel")
  if log_channel_id:
    channel = guild.get_channel(int(log_channel_id))
    if channel:
      try:
        await channel.send(embed=embed)
      except Exception:
        pass


def add_stat(guild_id, staff_id, action_type):
  data = load_data()
  g_id = str(guild_id)
  s_id = str(staff_id)
  if g_id not in data["modstats"]:
    data["modstats"][g_id] = {}
  if s_id not in data["modstats"][g_id]:
    data["modstats"][g_id][s_id] = {"jails": 0, "mutes": 0, "warns": 0, "bans": 0}
  if action_type in data["modstats"][g_id][s_id]:
    data["modstats"][g_id][s_id][action_type] += 1
  save_data(data)


def add_warn(guild_id, user_id, reason, staff_name):
  data = load_data()
  g_id = str(guild_id)
  u_id = str(user_id)
  if g_id not in data["warns"]:
    data["warns"][g_id] = {}
  if u_id not in data["warns"][g_id]:
    data["warns"][g_id][u_id] = []
  data["warns"][g_id][u_id].append({"reason": reason, "staff": str(staff_name)})
  save_data(data)


# --- Ticket Views & Claim System ---


class TicketControlView(discord.ui.View):

  def __init__(self):
    super().__init__(timeout=None)

  @discord.ui.button(label="Claim Ticket", style=discord.ButtonStyle.primary, custom_id="claim_ticket_btn")
  async def claim_ticket(self, interaction: discord.Interaction, button: discord.ui.Button):
    guild = interaction.guild
    staff_role_id = get_config(guild.id, "ticket_staff_role")
    senior_role_id = get_config(guild.id, "senior_role")
    staff_role_id_gen = get_config(guild.id, "staff_role")

    is_staff = False
    if interaction.user.guild_permissions.manage_messages:
      is_staff = True
    else:
      role_ids = [r.id for r in interaction.user.roles]
      if staff_role_id and int(staff_role_id) in role_ids:
        is_staff = True
      if senior_role_id and int(senior_role_id) in role_ids:
        is_staff = True
      if staff_role_id_gen and int(staff_role_id_gen) in role_ids:
        is_staff = True

    if not is_staff:
      await interaction.response.send_message("You do not have permission to claim tickets.", ephemeral=True)
      return

    channel = interaction.channel

    if staff_role_id:
      staff_role = guild.get_role(int(staff_role_id))
      if staff_role:
        await channel.set_permissions(staff_role, view_channel=True, send_messages=False, read_message_history=True)

    if staff_role_id_gen and staff_role_id_gen != staff_role_id:
      gen_role = guild.get_role(int(staff_role_id_gen))
      if gen_role:
        await channel.set_permissions(gen_role, view_channel=True, send_messages=False, read_message_history=True)

    await channel.set_permissions(interaction.user, view_channel=True, send_messages=True, read_message_history=True)

    button.disabled = True
    button.label = f"Claimed by {interaction.user.name}"
    button.style = discord.ButtonStyle.secondary

    await interaction.message.edit(view=self)
    await interaction.response.send_message(
        f"🔒 Ticket claimed by {interaction.user.mention}. Other staff can view this channel history, but **only you** can send messages."
    )

  @discord.ui.button(label="Close Ticket", style=discord.ButtonStyle.danger, custom_id="close_ticket_btn")
  async def close_ticket(self, interaction: discord.Interaction, button: discord.ui.Button):
    await interaction.response.send_message("Closing ticket in 5 seconds...")
    await asyncio.sleep(5)
    try:
      await interaction.channel.delete()
    except Exception:
      pass


class TicketSelect(discord.ui.Select):

  def __init__(self):
    options = [
        discord.SelectOption(label="Support", description="General assistance and questions", emoji="🛠️"),
        discord.SelectOption(label="Report", description="Report a user or staff member", emoji="🚨"),
        discord.SelectOption(label="Giveaway Claim", description="Claim a won giveaway prize", emoji="🎁"),
        discord.SelectOption(label="Giveaway Host", description="Coordinate hosting a giveaway", emoji="🎉"),
        discord.SelectOption(label="Ads/Partnerships", description="Inquiries regarding advertisements or partnerships", emoji="🤝"),
        discord.SelectOption(label="Decompile", description="Request code decompilation or uncopylocked file help", emoji="💻"),
    ]
    super().__init__(placeholder="Select a ticket category...", min_values=1, max_values=1, options=options, custom_id="ticket_dropdown")

  async def callback(self, interaction: discord.Interaction):
    guild = interaction.guild
    category_id = get_config(guild.id, "ticket_category")
    staff_role_id = get_config(guild.id, "ticket_staff_role")

    category = guild.get_channel(int(category_id)) if category_id else None
    overwrites = {
        guild.default_role: discord.PermissionOverwrite(view_channel=False),
        interaction.user: discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True),
        guild.me: discord.PermissionOverwrite(view_channel=True, send_messages=True, manage_channels=True),
    }

    if staff_role_id:
      staff_role = guild.get_role(int(staff_role_id))
      if staff_role:
        overwrites[staff_role] = discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True)

    ticket_channel = await guild.create_text_channel(
        name=f"ticket-{interaction.user.name}-{self.values[0].lower().replace('/', '-')}",
        category=category,
        overwrites=overwrites,
    )

    embed = discord.Embed(
        title=f"Ticket: {self.values[0]}",
        description=f"Welcome {interaction.user.mention}!\nSupport will be with you shortly.\nPlease describe your issue or request in detail.",
        color=discord.Color.blue(),
        timestamp=discord.utils.utcnow(),
    )

    view = TicketControlView()
    staff_ping = f"<@&{staff_role_id}>" if staff_role_id else ""
    
    await ticket_channel.send(content=f"{interaction.user.mention} {staff_ping}", embed=embed, view=view)
    await interaction.response.send_message(f"Your ticket has been created: {ticket_channel.mention}", ephemeral=True)


class TicketPanelView(discord.ui.View):

  def __init__(self):
    super().__init__(timeout=None)
    self.add_item(TicketSelect())


# --- Application System Modals & Views ---

class ApplicationModal(discord.ui.Modal):
  def __init__(self, app_type: str):
    super().__init__(title=f"Apply for: {app_type}")
    self.app_type = app_type

    if app_type == "Partnership":
      self.q1 = discord.ui.TextInput(
          label="What is your server/group about?",
          style=discord.TextStyle.long,
          placeholder="Tell us about your community or project...",
          required=True,
          max_length=500,
      )
      self.q2 = discord.ui.TextInput(
          label="What would you like to partner with us for?",
          style=discord.TextStyle.long,
          placeholder="Explain the partnership you are proposing...",
          required=True,
          max_length=500,
      )
      self.q3 = discord.ui.TextInput(
          label="Server/group link",
          style=discord.TextStyle.short,
          placeholder="Paste your invite or relevant link...",
          required=True,
          max_length=300,
      )
    else:  # Staff
      self.q1 = discord.ui.TextInput(
          label="Why do you want to join our staff team?",
          style=discord.TextStyle.long,
          placeholder="Explain why you would be a good staff member...",
          required=True,
          max_length=500,
      )
      self.q2 = discord.ui.TextInput(
          label="What staff experience do you have?",
          style=discord.TextStyle.long,
          placeholder="Tell us about your previous moderation/staff experience...",
          required=True,
          max_length=500,
      )
      self.q3 = discord.ui.TextInput(
          label="How active are you?",
          style=discord.TextStyle.short,
          placeholder="e.g. 2-4 hours per day",
          required=True,
          max_length=100,
      )

    self.add_item(self.q1)
    self.add_item(self.q2)
    self.add_item(self.q3)

  async def on_submit(self, interaction: discord.Interaction):
    guild = interaction.guild
    app_channel_id = get_config(guild.id, "app_log_channel")

    if not app_channel_id:
      await interaction.response.send_message(
          "❌ Application review channel has not been set up by staff yet.",
          ephemeral=True
      )
      return

    log_channel = guild.get_channel(int(app_channel_id))
    if not log_channel:
      await interaction.response.send_message(
          "❌ Configured application review channel could not be found.",
          ephemeral=True
      )
      return

    embed = discord.Embed(
        title=f"📄 New Application: {self.app_type}",
        color=discord.Color.gold(),
        timestamp=discord.utils.utcnow(),
    )
    embed.set_author(
        name=str(interaction.user),
        icon_url=interaction.user.display_avatar.url
    )
    embed.add_field(
        name="Applicant",
        value=f"{interaction.user.mention} (`{interaction.user.id}`)",
        inline=False
    )

    if self.app_type == "Partnership":
      embed.add_field(name="1. Community / Project", value=self.q1.value, inline=False)
      embed.add_field(name="2. Partnership Proposal", value=self.q2.value, inline=False)
      embed.add_field(name="3. Server / Group Link", value=self.q3.value, inline=False)
    else:
      embed.add_field(name="1. Why Staff?", value=self.q1.value, inline=False)
      embed.add_field(name="2. Staff Experience", value=self.q2.value, inline=False)
      embed.add_field(name="3. Activity", value=self.q3.value, inline=False)

    view = ApplicationReviewView(interaction.user.id)
    await log_channel.send(embed=embed, view=view)

    await interaction.response.send_message(
        "✅ Your application has been successfully submitted to the staff team!",
        ephemeral=True
    )


class ApplicationReviewView(discord.ui.View):
  def __init__(self, applicant_id: int):
    super().__init__(timeout=None)
    self.applicant_id = applicant_id

  @discord.ui.button(label="Accept", style=discord.ButtonStyle.green, custom_id="accept_app_btn")
  async def accept_app(self, interaction: discord.Interaction, button: discord.ui.Button):
    if not interaction.user.guild_permissions.manage_messages:
      await interaction.response.send_message(
          "You do not have permission to review applications.",
          ephemeral=True
      )
      return

    embed = interaction.message.embeds[0]
    embed.color = discord.Color.green()
    embed.add_field(
        name="Status",
        value=f"✅ **Accepted** by {interaction.user.mention}",
        inline=False
    )

    for child in self.children:
      child.disabled = True

    await interaction.message.edit(embed=embed, view=self)

    member = interaction.guild.get_member(self.applicant_id)
    if member:
      try:
        await member.send(
            f"🎉 Congratulations! Your **{embed.title.replace('📄 New Application: ', '')}** "
            f"application in **{interaction.guild.name}** has been **ACCEPTED**!"
        )
      except discord.Forbidden:
        pass

    await interaction.response.send_message(
        "Application accepted and user notified.",
        ephemeral=True
    )

  @discord.ui.button(label="Deny", style=discord.ButtonStyle.red, custom_id="deny_app_btn")
  async def deny_app(self, interaction: discord.Interaction, button: discord.ui.Button):
    if not interaction.user.guild_permissions.manage_messages:
      await interaction.response.send_message(
          "You do not have permission to review applications.",
          ephemeral=True
      )
      return

    embed = interaction.message.embeds[0]
    embed.color = discord.Color.red()
    embed.add_field(
        name="Status",
        value=f"❌ **Denied** by {interaction.user.mention}",
        inline=False
    )

    for child in self.children:
      child.disabled = True

    await interaction.message.edit(embed=embed, view=self)

    member = interaction.guild.get_member(self.applicant_id)
    if member:
      try:
        await member.send(
            f"Hello, thank you for applying to **{interaction.guild.name}**. "
            f"Unfortunately, your application was **DENIED** at this time."
        )
      except discord.Forbidden:
        pass

    await interaction.response.send_message(
        "Application denied and user notified.",
        ephemeral=True
    )


class ApplicationSelect(discord.ui.Select):
  def __init__(self):
    options = [
        discord.SelectOption(
            label="Staff",
            description="Apply to join the server staff team",
            emoji="🛡️"
        ),
        discord.SelectOption(
            label="Partnership",
            description="Apply for a partnership with our community",
            emoji="🤝"
        ),
    ]
    super().__init__(
        placeholder="Select an application type...",
        min_values=1,
        max_values=1,
        options=options,
        custom_id="app_dropdown"
    )

  async def callback(self, interaction: discord.Interaction):
    await interaction.response.send_modal(
        ApplicationModal(self.values[0])
    )


class ApplicationPanelView(discord.ui.View):
  def __init__(self):
    super().__init__(timeout=None)
    self.add_item(ApplicationSelect())


# --- Leveling Role Milestone Config View & Modal ---

class LevelRoleSelect(discord.ui.RoleSelect):
  def __init__(self, level: int):
    super().__init__(placeholder=f"Select role(s) to give at Level {level}...", min_values=1, max_values=5)
    self.level = level

  async def callback(self, interaction: discord.Interaction):
    guild_id = interaction.guild.id
    data = load_data()
    g_id = str(guild_id)
    if g_id not in data["levels"]:
      data["levels"][g_id] = {"roles": {}, "channel_id": None}

    selected_role_ids = [r.id for r in self.values]
    data["levels"][g_id]["roles"][str(self.level)] = selected_role_ids
    save_data(data)

    role_mentions = ", ".join([r.mention for r in self.values])
    await interaction.response.send_message(f"✅ Successfully linked role(s) {role_mentions} to **Level {self.level}**!", ephemeral=True)


class LevelRoleView(discord.ui.View):
  def __init__(self, level: int):
    super().__init__(timeout=180)
    self.add_item(LevelRoleSelect(level))


# --- Giveaway Views & Logic ---

async def end_giveaway_task_logic(bot, guild_id, message_id):
  data = load_data()
  g_id_str = str(guild_id)
  m_id_str = str(message_id)

  if g_id_str not in data["giveaways"] or m_id_str not in data["giveaways"][g_id_str]:
    return

  g_data = data["giveaways"][g_id_str][m_id_str]
  if g_data.get("ended", False):
    return

  g_data["ended"] = True
  save_data(data)

  guild = bot.get_guild(guild_id)
  if not guild:
    return
  channel = guild.get_channel(int(g_data["channel_id"]))
  if not channel:
    return

  try:
    message = await channel.fetch_message(message_id)
  except Exception:
    return

  participants = g_data.get("participants", [])
  winners_count = int(g_data.get("winners_count", 1))
  prize = g_data.get("prize", "Unknown Prize")

  if len(participants) > 0:
    actual_winners_count = min(winners_count, len(participants))
    winners = random.sample(participants, actual_winners_count)
    winners_mention = ", ".join([f"<@{w}>" for w in winners])
    
    embed = message.embeds[0]
    embed.color = discord.Color.dark_embed()
    embed.title = "🎉 GIVEAWAY ENDED 🎉"
    embed.add_field(name="Winners", value=winners_mention, inline=False)
    
    view = GiveawayView(guild_id, message_id, ended=True)
    await message.edit(embed=embed, view=view)
    await channel.send(f"🎊 Congratulations {winners_mention}! You won the **{prize}**!")
  else:
    embed = message.embeds[0]
    embed.color = discord.Color.dark_embed()
    embed.title = "🎉 GIVEAWAY ENDED (No Valid Entries) 🎉"
    embed.add_field(name="Winners", value="No participants entered.", inline=False)
    
    view = GiveawayView(guild_id, message_id, ended=True)
    await message.edit(embed=embed, view=view)
    await channel.send(f"The giveaway for **{prize}** ended with no participants.")


class GiveawayView(discord.ui.View):

  def __init__(self, guild_id, message_id, ended=False):
    super().__init__(timeout=None)
    self.guild_id = guild_id
    self.message_id = message_id
    if ended:
      self.join_btn.disabled = True
      self.end_btn.disabled = True

  @discord.ui.button(label="🎉 Enter Giveaway", style=discord.ButtonStyle.green, custom_id="enter_giveaway_btn")
  async def join_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
    data = load_data()
    g_id_str = str(self.guild_id)
    m_id_str = str(self.message_id)

    if g_id_str not in data["giveaways"] or m_id_str not in data["giveaways"][g_id_str]:
      await interaction.response.send_message("This giveaway no longer exists in records.", ephemeral=True)
      return

    g_data = data["giveaways"][g_id_str][m_id_str]
    if g_data.get("ended", False):
      await interaction.response.send_message("This giveaway has already ended!", ephemeral=True)
      return

    if "participants" not in g_data:
      g_data["participants"] = []

    user_id = interaction.user.id
    if user_id in g_data["participants"]:
      g_data["participants"].remove(user_id)
      save_data(data)
      await interaction.response.send_message("❌ You have left the giveaway.", ephemeral=True)
    else:
      g_data["participants"].append(user_id)
      save_data(data)
      await interaction.response.send_message("✅ You have successfully entered the giveaway! Good luck!", ephemeral=True)

  @discord.ui.button(label="End Early", style=discord.ButtonStyle.red, custom_id="end_giveaway_early_btn")
  async def end_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
    if not interaction.user.guild_permissions.administrator:
      await interaction.response.send_message("Only Administrators can end giveaways early.", ephemeral=True)
      return

    await interaction.response.send_message("Ending giveaway...", ephemeral=True)
    await end_giveaway_task_logic(interaction.client, self.guild_id, self.message_id)


@tasks.loop(seconds=15)
async def check_giveaways():
  data = load_data()
  now = datetime.now(timezone.utc)
  
  if "giveaways" not in data:
    return

  updated = False
  for g_id_str, messages in list(data["giveaways"].items()):
    for m_id_str, g_data in list(messages.items()):
      if g_data.get("ended", False):
        continue
      
      end_time = datetime.fromisoformat(g_data["end_time"])
      if now >= end_time:
        guild_id = int(g_id_str)
        message_id = int(m_id_str)
        await end_giveaway_task_logic(bot, guild_id, message_id)
        updated = True

  if updated:
    data = load_data()


# --- Appeal Views & Modals ---

class AppealModal(discord.ui.Modal, title="Submit Your Jail Appeal"):
  reason = discord.ui.TextInput(
      label="Why should your jail be revoked?",
      style=discord.TextStyle.long,
      placeholder="Explain your case clearly...",
      required=True,
      max_length=1000,
  )

  def __init__(self, guild_id):
    super().__init__()
    self.guild_id = guild_id

  async def on_submit(self, interaction: discord.Interaction):
    data = load_data()
    appeal_channel_id = get_config(self.guild_id, "appeal_channel")
    if not appeal_channel_id:
      await interaction.response.send_message(
          "Appeal channel is not configured on this server.", ephemeral=True
      )
      return

    g_id_str = str(self.guild_id)
    u_id_str = str(interaction.user.id)
    if g_id_str not in data["appeal_cooldowns"]:
      data["appeal_cooldowns"][g_id_str] = {}
    data["appeal_cooldowns"][g_id_str][u_id_str] = discord.utils.utcnow().isoformat()
    save_data(data)

    guild = bot.get_guild(self.guild_id)
    channel = guild.get_channel(int(appeal_channel_id))

    proof_url = data.get("temp_proof", {}).get(u_id_str)
    j_info = data.get("jail_info", {}).get(g_id_str, {}).get(u_id_str, {"reason": "Not specified", "staff": "Unknown"})

    embed = discord.Embed(
        title="New Jail Appeal Submitted",
        color=discord.Color.orange(),
        timestamp=discord.utils.utcnow(),
    )
    embed.add_field(name="User", value=f"{interaction.user} ({interaction.user.id})", inline=False)
    embed.add_field(name="Jailed By", value=j_info["staff"], inline=True)
    embed.add_field(name="Jail Reason", value=j_info["reason"], inline=True)
    embed.add_field(name="Appeal Reason", value=self.reason.value, inline=False)
    if proof_url:
      embed.set_image(url=proof_url)

    view = SeniorReviewView(interaction.user.id, self.guild_id)
    await channel.send(embed=embed, view=view)
    await interaction.response.send_message(
        "Your appeal has been successfully sent to the senior staff team!", ephemeral=True
    )


class AppealButtonView(discord.ui.View):

  def __init__(self, guild_id):
    super().__init__(timeout=None)
    self.guild_id = guild_id

  @discord.ui.button(label="Appeal Jail", style=discord.ButtonStyle.primary, custom_id="appeal_jail_btn")
  async def appeal_button(self, interaction: discord.Interaction, button: discord.ui.Button):
    data = load_data()
    g_id_str = str(self.guild_id)
    u_id_str = str(interaction.user.id)

    cooldowns = data.get("appeal_cooldowns", {}).get(g_id_str, {})
    last_appeal = cooldowns.get(u_id_str)

    if last_appeal:
      last_time = datetime.fromisoformat(last_appeal)
      now = discord.utils.utcnow()
      elapsed_seconds = (now - last_time).total_seconds()
      cooldown_limit = 6 * 3600

      if elapsed_seconds < cooldown_limit:
        remaining = int(cooldown_limit - elapsed_seconds)
        hours = remaining // 3600
        minutes = (remaining % 3600) // 60
        await interaction.response.send_message(
            f"You are on an appeal cooldown. You must wait **{hours}h {minutes}m** before submitting another appeal.",
            ephemeral=True,
        )
        return

    await interaction.response.send_modal(AppealModal(self.guild_id))


class ActionReasonModal(discord.ui.Modal):

  def __init__(self, action_type, target_user_id, guild_id):
    title = "Accept Appeal Reason" if action_type == "accept" else "Deny Appeal Reason"
    super().__init__(title=title)
    self.action_type = action_type
    self.target_user_id = target_user_id
    self.guild_id = guild_id

    self.reason_input = discord.ui.TextInput(
        label="Reason for decision",
        style=discord.TextStyle.long,
        placeholder="Type your reason here...",
        required=True,
        max_length=500,
    )
    self.add_item(self.reason_input)

  async def on_submit(self, interaction: discord.Interaction):
    senior_role_id = get_config(self.guild_id, "senior_role")
    if not senior_role_id or not any(r.id == int(senior_role_id) for r in interaction.user.roles):
      await interaction.response.send_message("Only Senior Moderators can use this.", ephemeral=True)
      return

    guild = bot.get_guild(self.guild_id)
    member = guild.get_member(self.target_user_id)
    reason_text = self.reason_input.value

    if self.action_type == "accept":
      jail_role_id = get_config(self.guild_id, "jail_role")
      if member and jail_role_id:
        jail_role = guild.get_role(int(jail_role_id))
        if jail_role:
          await member.remove_roles(jail_role)

      if member:
        try:
          await member.send(
              f"Your jail appeal in **{guild.name}** has been **ACCEPTED** by {interaction.user.mention}.\n**Reason:** {reason_text}"
          )
        except discord.Forbidden:
          pass

      embed = interaction.message.embeds[0]
      embed.color = discord.Color.green()
      embed.add_field(name="Status", value=f"Accepted by {interaction.user.mention}\n**Reason:** {reason_text}", inline=False)
      
      log_embed = discord.Embed(title="Appeal Accepted", color=discord.Color.green(), timestamp=discord.utils.utcnow())
      log_embed.add_field(name="User", value=f"{member} ({self.target_user_id})", inline=False)
      log_embed.add_field(name="Accepted By", value=str(interaction.user), inline=False)
      log_embed.add_field(name="Reason", value=reason_text, inline=False)
      await send_log(guild, log_embed)

    else:
      if member:
        try:
          await member.send(
              f"Your jail appeal in **{guild.name}** has been **DENIED** by {interaction.user.mention}.\n**Reason:** {reason_text}"
          )
        except discord.Forbidden:
          pass

      embed = interaction.message.embeds[0]
      embed.color = discord.Color.red()
      embed.add_field(name="Status", value=f"Denied by {interaction.user.mention}\n**Reason:** {reason_text}", inline=False)

      log_embed = discord.Embed(title="Appeal Denied", color=discord.Color.red(), timestamp=discord.utils.utcnow())
      log_embed.add_field(name="User", value=f"{member} ({self.target_user_id})", inline=False)
      log_embed.add_field(name="Denied By", value=str(interaction.user), inline=False)
      log_embed.add_field(name="Reason", value=reason_text, inline=False)
      await send_log(guild, log_embed)

    view = SeniorReviewView(self.target_user_id, self.guild_id)
    for child in view.children:
      child.disabled = True

    await interaction.message.edit(embed=embed, view=view)
    status_msg = "Appeal accepted, user unjailed, and notified." if self.action_type == "accept" else "Appeal denied and user notified."
    await interaction.response.send_message(status_msg, ephemeral=True)


class SeniorReviewView(discord.ui.View):

  def __init__(self, target_user_id, guild_id):
    super().__init__(timeout=None)
    self.target_user_id = target_user_id
    self.guild_id = guild_id

  @discord.ui.button(label="Accept", style=discord.ButtonStyle.green, custom_id="accept_appeal")
  async def accept_appeal(self, interaction: discord.Interaction, button: discord.ui.Button):
    senior_role_id = get_config(self.guild_id, "senior_role")
    if not senior_role_id or not any(r.id == int(senior_role_id) for r in interaction.user.roles):
      await interaction.response.send_message("Only Senior Moderators can use this.", ephemeral=True)
      return
    await interaction.response.send_modal(ActionReasonModal("accept", self.target_user_id, self.guild_id))

  @discord.ui.button(label="Deny", style=discord.ButtonStyle.red, custom_id="deny_appeal")
  async def deny_appeal(self, interaction: discord.Interaction, button: discord.ui.Button):
    senior_role_id = get_config(self.guild_id, "senior_role")
    if not senior_role_id or not any(r.id == int(senior_role_id) for r in interaction.user.roles):
      await interaction.response.send_message("Only Senior Moderators can use this.", ephemeral=True)
      return
    await interaction.response.send_modal(ActionReasonModal("deny", self.target_user_id, self.guild_id))


# --- Check Helpers ---
async def check_staff(ctx):
  staff_role_id = get_config(ctx.guild.id, "staff_role")
  senior_role_id = get_config(ctx.guild.id, "senior_role")
  if not staff_role_id and not senior_role_id:
    return ctx.author.guild_permissions.manage_messages
  role_ids = [r.id for r in ctx.author.roles]
  return (
      (staff_role_id and int(staff_role_id) in role_ids)
      or (senior_role_id and int(senior_role_id) in role_ids)
      or ctx.author.guild_permissions.manage_messages
  )


async def check_senior(ctx):
  senior_role_id = get_config(ctx.guild.id, "senior_role")
  if not senior_role_id:
    return ctx.author.guild_permissions.manage_messages
  role_ids = [r.id for r in ctx.author.roles]
  return (senior_role_id and int(senior_role_id) in role_ids) or ctx.author.guild_permissions.manage_messages


# --- Configuration Commands (Prefix & Slash Setup) ---
@bot.command()
@commands.has_permissions(administrator=True)
async def setappeal(ctx, channel: discord.TextChannel):
  set_config(ctx.guild.id, "appeal_channel", channel.id)
  await ctx.send(f"Appeal channel set to {channel.mention}")


@bot.command()
@commands.has_permissions(administrator=True)
async def setsenior(ctx, role: discord.Role):
  set_config(ctx.guild.id, "senior_role", role.id)
  await ctx.send(f"Senior Mod role set to {role.name}")


@bot.command()
@commands.has_permissions(administrator=True)
async def setstaff(ctx, role: discord.Role):
  set_config(ctx.guild.id, "staff_role", role.id)
  await ctx.send(f"Staff role set to {role.name}")


@bot.command()
@commands.has_permissions(administrator=True)
async def setjail(ctx, role: discord.Role):
  set_config(ctx.guild.id, "jail_role", role.id)
  await ctx.send(f"Jail role set to {role.name}")


@bot.command()
@commands.has_permissions(administrator=True)
async def setlogs(ctx, channel: discord.TextChannel):
  set_config(ctx.guild.id, "log_channel", channel.id)
  await ctx.send(f"Logs channel set to {channel.mention}")


# --- Application Setup Slash Commands ---
@bot.tree.command(name="setupapps", description="Deploy the application panel and configure the review channel.")
@discord.app_commands.describe(
    panel_channel="The channel where users will see the application dropdown menu",
    review_channel="The staff channel where completed applications will be sent for review"
)
@discord.app_commands.checks.has_permissions(administrator=True)
async def setupapps(interaction: discord.Interaction, panel_channel: discord.TextChannel, review_channel: discord.TextChannel):
  set_config(interaction.guild.id, "app_log_channel", review_channel.id)

  embed = discord.Embed(
      title="📋 Community Applications",
      description=(
          "Want to join our team or contribute to the community? "
          "Select an application category from the dropdown menu below to get started!\n\n"
          "• **Trial Moderator:** Moderate chat and keep the server safe.\n"
          "• **Content Creator:** Create videos, streams, or graphics.\n"
          "• **Event Host:** Run community events and giveaways.\n"
          "• **Leaker:** Share uncopylocked Roblox games and assets."
      ),
      color=discord.Color.blurple(),
      timestamp=discord.utils.utcnow()
  )
  embed.set_footer(text=interaction.guild.name, icon_url=interaction.guild.icon.url if interaction.guild.icon else None)

  view = ApplicationPanelView()
  await panel_channel.send(embed=embed, view=view)

  await interaction.response.send_message(
      f"✅ Application panel successfully deployed to {panel_channel.mention}!\nReview channel set to {review_channel.mention}.",
      ephemeral=True
  )


# --- Leveling System Config Commands ---
@bot.command()
@commands.has_permissions(administrator=True)
async def setlevelchannel(ctx, channel: discord.TextChannel):
  data = load_data()
  g_id = str(ctx.guild.id)
  if g_id not in data["levels"]:
    data["levels"][g_id] = {"roles": {}, "channel_id": None}
  data["levels"][g_id]["channel_id"] = channel.id
  save_data(data)
  await ctx.send(f"✅ Level-up notification channel set to {channel.mention}")


@bot.command()
@commands.has_permissions(administrator=True)
async def setlevelrole(ctx, level: int):
  try:
    view = LevelRoleView(level)
    await ctx.send(f"👇 Use the dropdown menu below to select role(s) for **Level {level}**:", view=view)
  except Exception as e:
    await ctx.send(f"❌ Failed to open the role selection menu: {e}")


# --- Ticket System Setup Commands ---
@bot.command()
@commands.has_permissions(administrator=True)
async def setupticket(ctx, channel: discord.TextChannel):
  embed = discord.Embed(
      title="Support Tickets",
      description="Select a category from the dropdown menu below to open a private ticket with our staff team.",
      color=discord.Color.blurple(),
  )
  view = TicketPanelView()
  await channel.send(embed=embed, view=view)
  await ctx.send(f"Ticket panel successfully sent to {channel.mention}!")


@bot.command()
@commands.has_permissions(administrator=True)
async def setcategory(ctx, category: discord.CategoryChannel):
  set_config(ctx.guild.id, "ticket_category", category.id)
  await ctx.send(f"Ticket category set to **{category.name}**")


@bot.command()
@commands.has_permissions(administrator=True)
async def setstaffrole(ctx, role: discord.Role):
  set_config(ctx.guild.id, "ticket_staff_role", role.id)
  await ctx.send(f"Ticket staff role set to {role.mention}")


# --- Giveaway Slash Command ---
@bot.tree.command(name="gstart", description="Start a community giveaway.")
@discord.app_commands.describe(
    channel="The channel where the giveaway will be posted",
    duration="How long the giveaway runs (e.g., 30s, 10m, 2h, 1d)",
    winners="The number of winners to pick",
    prize="The prize being given away"
)
@discord.app_commands.checks.has_permissions(administrator=True)
async def gstart(interaction: discord.Interaction, channel: discord.TextChannel, duration: str, winners: int, prize: str):
  seconds = 0
  match = re.match(r"(\d+)([smhd])", duration)
  if not match:
    await interaction.response.send_message("❌ Invalid duration format! Use `s`, `m`, `h`, or `d` (e.g., `10m`, `2h`).", ephemeral=True)
    return

  amount, unit = match.groups()
  amount = int(amount)
  if unit == 's':
    seconds = amount
  elif unit == 'm':
    seconds = amount * 60
  elif unit == 'h':
    seconds = amount * 3600
  elif unit == 'd':
    seconds = amount * 86400

  end_time = datetime.now(timezone.utc) + timedelta(seconds=seconds)
  timestamp_unix = int(end_time.timestamp())

  await interaction.response.send_message(f"✅ Starting giveaway in {channel.mention}...", ephemeral=True)

  embed = discord.Embed(
      title="🎉 **GIVEAWAY** 🎉",
      description=f"Prize: **{prize}**\nHosted by: {interaction.user.mention}\nWinners: **{winners}**\nEnds:  ()",
      color=discord.Color.gold(),
      timestamp=discord.utils.utcnow()
  )

  view = GiveawayView(interaction.guild.id, 0)
  
  try:
    g_msg = await channel.send(embed=embed, view=view)
  except Exception as e:
    print(f"Failed to send giveaway message: {e}")
    return

  data = load_data()
  g_id_str = str(interaction.guild.id)
  m_id_str = str(g_msg.id)

  if g_id_str not in data["giveaways"]:
    data["giveaways"][g_id_str] = {}

  data["giveaways"][g_id_str][m_id_str] = {
      "prize": prize,
      "winners_count": winners,
      "end_time": end_time.isoformat(),
      "channel_id": channel.id,
      "participants": [],
      "ended": False
  }
  save_data(data)

  view.message_id = g_msg.id
  await g_msg.edit(view=view)


# --- Bot Announcement Command for Staff ---
@bot.command(name="announcebot")
async def announcebot(ctx):
  if not await check_staff(ctx):
    await ctx.send("You do not have permission to use this command.", delete_after=5)
    return

  try:
    await ctx.message.delete()
  except Exception:
    pass

  embed = discord.Embed(
      title="🤖 Meet Our New Server Bot!",
      description=(
          "We are excited to introduce our brand new server utility and management bot! "
          "It has been custom-built to improve your experience and streamline server activities."
      ),
      color=discord.Color.blurple(),
      timestamp=discord.utils.utcnow()
  )

  embed.add_field(
      name="🛠️ What Can It Do?",
      value=(
          "• **Ticket Support:** Open private tickets (including Decompile requests) using our interactive panel.\n"
          "• **Applications:** Apply for Staff or Partnership through the application panel.\n"
          "• **Leveling System:** Earn XP by chatting and unlock exclusive milestone roles.\n"
          "• **Giveaways:** Participate in exciting community giveaways easily.\n"
          "• **Moderation & Security:** Keeps the community safe and clean."
      ),
      inline=False
  )

  embed.add_field(
      name="📌 Quick Tip",
      value="All regular bot commands use `>`, and panel setups use slash commands like `/setupapps` and `/gstart`!",
      inline=False
  )

  embed.set_footer(text=f"Announcement by {ctx.author}", icon_url=ctx.author.display_avatar.url)
  await ctx.send(embed=embed)



# --- Custom Help Command ---
@bot.command(name="help")
async def help_command(ctx):
  embed = discord.Embed(
      title="🛡️ Moderation & Security Help",
      description="All commands use the `>` prefix.",
      color=discord.Color.blurple(),
  )
  embed.add_field(name="🔨 Moderation", value=(
      "`>warn @user [reason]` — Warn\n"
      "`>warns [@user]` — View warnings\n"
      "`>delwarn @user <number>` — Remove one warning\n"
      "`>clearwarns @user` — Clear all warnings\n"
      "`>mute @user [reason]` — 10-minute timeout\n"
      "`>timeout @user <10m/2h/1d> [reason]` — Timeout\n"
      "`>unmute @user` — Remove timeout\n"
      "`>kick @user [reason]` — Kick\n"
      "`>ban @user [reason]` — Ban\n"
      "`>softban @user [reason]` — Ban + unban\n"
      "`>unban <user ID>` — Unban\n"
      "`>purge <1-100>` — Delete messages\n"
      "`>purgeuser @user [amount]` — Delete a user's messages\n"
      "`>jail @user [reason]` / `>unjail @user` — Jail controls\n"
      "`>slowmode <seconds>` — Set slowmode\n"
      "`>lock` / `>unlock` — Lock/unlock channel\n"
      "`>nick @user [nickname]` — Change nickname\n"
      "`>roleadd @user @role` / `>roleremove @user @role` — Manage roles"
  ), inline=False)
  embed.add_field(name="🛡️ Security", value=(
      "`>security` — Security status\n"
      "`>security on/off` — Enable or disable security\n"
      "`>securitymode strict/normal` — Security mode\n"
      "`>securitysetting <setting> <on/off>` — Toggle protection\n"
      "`>allowbot @bot` / `>removebot @bot` — Bot whitelist\n\n"
      "Protections: anti-spam, anti-links, anti-invites, anti-mass-mentions, anti-caps, duplicate-spam, anti-raid and optional anti-bot."
  ), inline=False)
  embed.add_field(name="📊 Information", value="`>ms [@user]` — Mod statistics\n`>userinfo [@user]` — User info\n`>serverinfo` — Server info", inline=False)
  embed.add_field(name="⚙️ Setup", value=(
      "`>setlogs #channel`\n`>setstaff @role`\n`>setsenior @role`\n`>setjail @role`\n"
      "`>setappeal #channel`\n`>setstaffrole @role`\n`>setcategory <category>`\n"
      "`>setreaction #channel <emoji>` — Auto-react to messages\n"
      "`>reaction` — View auto-reaction status\n"
      "`>setreaction off` — Disable auto-reactions"
  ), inline=False)
  await ctx.send(embed=embed)


# --- Strict Security & Extended Moderation ---
SECURITY_DEFAULTS = {
    "security_enabled": True,
    "anti_spam": True,
    "anti_links": True,
    "anti_invites": True,
    "anti_mass_mentions": True,
    "anti_caps": True,
    "anti_duplicate": True,
    "anti_raid": True,
    "anti_bots": False,
    "strict_mode": True,
    "spam_limit": 5,
    "spam_window": 8,
    "duplicate_limit": 3,
    "raid_limit": 6,
    "raid_window": 20,
    "blocked_links_action": "delete_warn",
    "security_whitelist": [],
    "reaction_channel": None,
    "reaction_emoji": None,
}

_message_tracker = defaultdict(lambda: defaultdict(deque))
_duplicate_tracker = defaultdict(lambda: defaultdict(deque))
_join_tracker = defaultdict(deque)


def security_config(guild_id):
  data = load_data()
  g_id = str(guild_id)
  cfg = data["guilds"].setdefault(g_id, {})
  changed = False
  for key, value in SECURITY_DEFAULTS.items():
    if key not in cfg:
      cfg[key] = value
      changed = True
  if changed:
    save_data(data)
  return cfg


def set_security_config(guild_id, key, value):
  data = load_data()
  g_id = str(guild_id)
  data["guilds"].setdefault(g_id, {})[key] = value
  save_data(data)


def is_security_exempt(member):
  if member.guild_permissions.administrator or member.guild_permissions.manage_guild:
    return True
  cfg = security_config(member.guild.id)
  staff_id = cfg.get("staff_role")
  senior_id = cfg.get("senior_role")
  return any(
      rid and any(role.id == int(rid) for role in member.roles)
      for rid in (staff_id, senior_id)
  )


async def security_log(guild, title, description, color=discord.Color.red()):
  embed = discord.Embed(title=title, description=description, color=color, timestamp=discord.utils.utcnow())
  embed.set_footer(text="Security System")
  await send_log(guild, embed)


async def can_moderate(ctx, member):
  if member.id == ctx.author.id:
    await ctx.send("❌ You cannot moderate yourself.", delete_after=5)
    return False
  if member.id == ctx.guild.owner_id:
    await ctx.send("❌ You cannot moderate the server owner.", delete_after=5)
    return False
  if ctx.author.id != ctx.guild.owner_id and member.top_role >= ctx.author.top_role:
    await ctx.send("❌ You can only moderate members below your highest role.", delete_after=5)
    return False
  if ctx.guild.me and member.top_role >= ctx.guild.me.top_role:
    await ctx.send("❌ My bot role must be higher than the target's highest role.", delete_after=5)
    return False
  return True


def parse_duration(value):
  match = re.fullmatch(r"(\d+)(s|m|h|d)", value.lower().strip())
  if not match:
    return None
  amount, unit = int(match.group(1)), match.group(2)
  multiplier = {"s": 1, "m": 60, "h": 3600, "d": 86400}[unit]
  seconds = amount * multiplier
  if seconds < 1 or seconds > 28 * 86400:
    return None
  return seconds



# --- Auto Reaction System ---
@bot.command(name="setreaction")
@commands.has_permissions(administrator=True)
async def setreaction(ctx, channel: discord.TextChannel = None, *, emoji: str = None):
  """Set the channel and emoji used for automatic reactions."""
  if channel is None and emoji is None:
    await ctx.send(
        "❌ Usage: `>setreaction #channel <emoji>`\n"
        "Example: `>setreaction #general 👍`\n"
        "Disable with: `>setreaction off`"
    )
    return

  if channel is None and emoji and emoji.lower().strip() == "off":
    set_security_config(ctx.guild.id, "reaction_channel", None)
    set_security_config(ctx.guild.id, "reaction_emoji", None)
    await ctx.send("✅ Automatic reactions have been disabled.")
    return

  if channel is None or not emoji:
    await ctx.send(
        "❌ Usage: `>setreaction #channel <emoji>`\n"
        "Example: `>setreaction #general 👍`"
    )
    return

  emoji = emoji.strip()

  # Test the emoji before saving it.
  try:
    await ctx.message.add_reaction(emoji)
  except (discord.HTTPException, discord.Forbidden):
    await ctx.send(
        "❌ I couldn't use that emoji. Make sure it is valid and that "
        "I have permission to add reactions."
    )
    return

  set_security_config(ctx.guild.id, "reaction_channel", channel.id)
  set_security_config(ctx.guild.id, "reaction_emoji", emoji)

  await ctx.send(
      f"✅ Automatic reaction set!\n"
      f"**Channel:** {channel.mention}\n"
      f"**Reaction:** {emoji}"
  )


@bot.command(name="reaction")
@commands.has_permissions(administrator=True)
async def reaction_status(ctx):
  cfg = security_config(ctx.guild.id)
  channel_id = cfg.get("reaction_channel")
  emoji = cfg.get("reaction_emoji")

  if not channel_id or not emoji:
    await ctx.send("ℹ️ Automatic reactions are currently disabled.")
    return

  channel = ctx.guild.get_channel(int(channel_id))
  channel_text = channel.mention if channel else f"`{channel_id}`"
  await ctx.send(
      f"🔄 **Auto Reaction Status**\n"
      f"**Channel:** {channel_text}\n"
      f"**Reaction:** {emoji}"
  )


@bot.command(name="security")
@commands.has_permissions(administrator=True)
async def security(ctx, action: str = "status"):
  cfg = security_config(ctx.guild.id)
  action = action.lower()
  if action in ("on", "enable", "enabled"):
    set_security_config(ctx.guild.id, "security_enabled", True)
    await ctx.send("🛡️ **Strict Security System enabled.**")
    return
  if action in ("off", "disable", "disabled"):
    set_security_config(ctx.guild.id, "security_enabled", False)
    await ctx.send("⚠️ **Strict Security System disabled.**")
    return
  if action != "status":
    await ctx.send("Usage: `>security on`, `>security off`, or `>security status`")
    return
  embed = discord.Embed(title="🛡️ Security Status", color=discord.Color.green() if cfg["security_enabled"] else discord.Color.red())
  embed.add_field(name="System", value="🟢 ON" if cfg["security_enabled"] else "🔴 OFF", inline=False)
  embed.add_field(name="Anti-Spam", value="ON" if cfg["anti_spam"] else "OFF", inline=True)
  embed.add_field(name="Anti-Links", value="ON" if cfg["anti_links"] else "OFF", inline=True)
  embed.add_field(name="Anti-Invites", value="ON" if cfg["anti_invites"] else "OFF", inline=True)
  embed.add_field(name="Anti-Raid", value="ON" if cfg["anti_raid"] else "OFF", inline=True)
  embed.add_field(name="Anti-Bots", value="ON" if cfg["anti_bots"] else "OFF", inline=True)
  embed.add_field(name="Strict Mode", value="ON" if cfg["strict_mode"] else "OFF", inline=True)
  await ctx.send(embed=embed)


@bot.command(name="securitymode")
@commands.has_permissions(administrator=True)
async def securitymode(ctx, mode: str):
  mode = mode.lower()
  if mode not in ("strict", "normal"):
    await ctx.send("Usage: `>securitymode strict` or `>securitymode normal`")
    return
  set_security_config(ctx.guild.id, "strict_mode", mode == "strict")
  await ctx.send(f"🛡️ Security mode set to **{mode.upper()}**.")


@bot.command(name="securitysetting")
@commands.has_permissions(administrator=True)
async def securitysetting(ctx, setting: str, state: str):
  allowed = {"antispam": "anti_spam", "antilinks": "anti_links", "antiinvite": "anti_invites",
             "antimentions": "anti_mass_mentions", "anticaps": "anti_caps", "antiduplicate": "anti_duplicate",
             "antiraid": "anti_raid", "antibots": "anti_bots"}
  key = allowed.get(setting.lower())
  if not key or state.lower() not in ("on", "off"):
    await ctx.send("Usage: `>securitysetting <antispam|antilinks|antiinvite|antimentions|anticaps|antiduplicate|antiraid|antibots> <on|off>`")
    return
  set_security_config(ctx.guild.id, key, state.lower() == "on")
  await ctx.send(f"🛡️ **{key.replace('_', ' ').title()}** set to **{state.upper()}**.")


@bot.command(name="allowbot")
@commands.has_permissions(administrator=True)
async def allowbot(ctx, member: discord.Member):
  if not member.bot:
    await ctx.send("❌ That member is not a bot.")
    return
  cfg = security_config(ctx.guild.id)
  whitelist = cfg.get("security_whitelist", [])
  if member.id not in whitelist:
    whitelist.append(member.id)
  set_security_config(ctx.guild.id, "security_whitelist", whitelist)
  await ctx.send(f"✅ {member.mention} is now whitelisted from anti-bot protection.")


@bot.command(name="removebot")
@commands.has_permissions(administrator=True)
async def removebot(ctx, member: discord.Member):
  cfg = security_config(ctx.guild.id)
  whitelist = cfg.get("security_whitelist", [])
  if member.id in whitelist:
    whitelist.remove(member.id)
  set_security_config(ctx.guild.id, "security_whitelist", whitelist)
  await ctx.send(f"✅ {member.mention} was removed from the bot whitelist.")


@bot.command(name="ban")
async def ban(ctx, member: discord.Member, *, reason: str = "No reason provided"):
  if not await check_staff(ctx) or not ctx.author.guild_permissions.ban_members:
    await ctx.send("❌ You need the configured staff role and **Ban Members** permission.", delete_after=5)
    return
  if not await can_moderate(ctx, member):
    return
  try:
    await member.send(f"You were banned from **{ctx.guild.name}**. Reason: {reason}")
  except discord.Forbidden:
    pass
  await member.ban(reason=reason, delete_message_days=1)
  add_stat(ctx.guild.id, ctx.author.id, "bans")
  await security_log(ctx.guild, "🔨 Member Banned", f"**User:** {member} (`{member.id}`)\n**Staff:** {ctx.author}\n**Reason:** {reason}")
  await ctx.send(f"🔨 Banned **{member}**.")



@bot.command(name="softban")
async def softban(ctx, member: discord.Member, *, reason: str = "No reason provided"):
  if not await check_staff(ctx) or not ctx.author.guild_permissions.ban_members:
    await ctx.send("❌ You need the configured staff role and **Ban Members** permission.", delete_after=5)
    return
  if not await can_moderate(ctx, member):
    return
  try:
    await member.send(f"You were removed from **{ctx.guild.name}**. Reason: {reason}")
  except discord.Forbidden:
    pass
  await member.ban(reason=f"Softban: {reason}", delete_message_days=1)
  user = await bot.fetch_user(member.id)
  await ctx.guild.unban(user, reason="Softban removal")
  await security_log(ctx.guild, "🧹 Member Softbanned", f"**User:** {member} (`{member.id}`)\n**Staff:** {ctx.author}\n**Reason:** {reason}")
  await ctx.send(f"🧹 Softbanned **{member}**.")

@bot.command(name="unban")
@commands.has_permissions(ban_members=True)
async def unban(ctx, user_id: int, *, reason: str = "No reason provided"):
  try:
    user = await bot.fetch_user(user_id)
    await ctx.guild.unban(user, reason=reason)
  except discord.NotFound:
    await ctx.send("❌ That user is not banned or could not be found.", delete_after=5)
    return
  await security_log(ctx.guild, "🔓 Member Unbanned", f"**User:** {user} (`{user.id}`)\n**Staff:** {ctx.author}\n**Reason:** {reason}", discord.Color.green())
  await ctx.send(f"🔓 Unbanned **{user}**.")


@bot.command(name="kick")
async def kick(ctx, member: discord.Member, *, reason: str = "No reason provided"):
  if not await check_staff(ctx) or not ctx.author.guild_permissions.kick_members:
    await ctx.send("❌ You need the configured staff role and **Kick Members** permission.", delete_after=5)
    return
  if not await can_moderate(ctx, member):
    return
  try:
    await member.send(f"You were kicked from **{ctx.guild.name}**. Reason: {reason}")
  except discord.Forbidden:
    pass
  await member.kick(reason=reason)
  await security_log(ctx.guild, "👢 Member Kicked", f"**User:** {member} (`{member.id}`)\n**Staff:** {ctx.author}\n**Reason:** {reason}")
  await ctx.send(f"👢 Kicked **{member}**.")


@bot.command(name="timeout")
async def timeout_member(ctx, member: discord.Member, duration: str, *, reason: str = "No reason provided"):
  if not await check_staff(ctx) or not ctx.author.guild_permissions.moderate_members:
    await ctx.send("❌ You need the configured staff role and **Timeout Members** permission.", delete_after=5)
    return
  if not await can_moderate(ctx, member):
    return
  seconds = parse_duration(duration)
  if seconds is None:
    await ctx.send("❌ Duration must be between 1 second and 28 days, e.g. `10m`, `2h`, `1d`.", delete_after=6)
    return
  until = discord.utils.utcnow() + timedelta(seconds=seconds)
  await member.timeout(until, reason=reason)
  add_stat(ctx.guild.id, ctx.author.id, "mutes")
  await security_log(ctx.guild, "⏱️ Member Timed Out", f"**User:** {member} (`{member.id}`)\n**Staff:** {ctx.author}\n**Duration:** `{duration}`\n**Reason:** {reason}", discord.Color.orange())
  await ctx.send(f"⏱️ Timed out {member.mention} for **{duration}**.")


@bot.command(name="unmute")
async def unmute(ctx, member: discord.Member, *, reason: str = "No reason provided"):
  if not await check_staff(ctx) or not ctx.author.guild_permissions.moderate_members:
    await ctx.send("❌ You need the configured staff role and **Timeout Members** permission.", delete_after=5)
    return
  if not await can_moderate(ctx, member):
    return
  await member.timeout(None, reason=reason)
  await security_log(ctx.guild, "🔊 Timeout Removed", f"**User:** {member} (`{member.id}`)\n**Staff:** {ctx.author}\n**Reason:** {reason}", discord.Color.green())
  await ctx.send(f"🔊 Removed timeout from {member.mention}.")


@bot.command(name="clearwarns")
async def clearwarns(ctx, member: discord.Member):
  if not await check_senior(ctx):
    await ctx.send("❌ Only Senior Moderators can clear warnings.", delete_after=5)
    return
  data = load_data()
  data.setdefault("warns", {}).setdefault(str(ctx.guild.id), {})[str(member.id)] = []
  save_data(data)
  await security_log(ctx.guild, "🧹 Warnings Cleared", f"**User:** {member} (`{member.id}`)\n**Staff:** {ctx.author}", discord.Color.green())
  await ctx.send(f"🧹 Cleared all warnings for {member.mention}.")


@bot.command(name="delwarn")
async def delwarn(ctx, member: discord.Member, number: int):
  if not await check_senior(ctx):
    await ctx.send("❌ Only Senior Moderators can remove warnings.", delete_after=5)
    return
  data = load_data()
  warnings = data.get("warns", {}).get(str(ctx.guild.id), {}).get(str(member.id), [])
  if number < 1 or number > len(warnings):
    await ctx.send("❌ Invalid warning number.", delete_after=5)
    return
  removed = warnings.pop(number - 1)
  save_data(data)
  await ctx.send(f"🧹 Removed warning **#{number}** from {member.mention}: {removed.get('reason', 'No reason')}")


@bot.command(name="purgeuser")
async def purgeuser(ctx, member: discord.Member, amount: int = 20):
  if not await check_senior(ctx):
    await ctx.send("❌ Only Senior Moderators can use this command.", delete_after=5)
    return
  if amount < 1 or amount > 100:
    await ctx.send("❌ Amount must be 1–100.", delete_after=5)
    return
  deleted = await ctx.channel.purge(limit=amount, check=lambda m: m.author.id == member.id)
  await security_log(ctx.guild, "🧹 User Messages Purged", f"**User:** {member} (`{member.id}`)\n**Staff:** {ctx.author}\n**Count:** {len(deleted)}", discord.Color.purple())
  await ctx.send(f"🧹 Deleted **{len(deleted)}** messages from {member.mention}.", delete_after=5)


@bot.command(name="slowmode")
@commands.has_permissions(manage_channels=True)
async def slowmode(ctx, seconds: int):
  if seconds < 0 or seconds > 21600:
    await ctx.send("❌ Slowmode must be between 0 and 21600 seconds.", delete_after=5)
    return
  await ctx.channel.edit(slowmode_delay=seconds)
  await security_log(ctx.guild, "🐢 Slowmode Changed", f"**Channel:** {ctx.channel.mention}\n**Staff:** {ctx.author}\n**Delay:** `{seconds}s`", discord.Color.blurple())
  await ctx.send(f"🐢 Slowmode set to **{seconds}s**.", delete_after=5)


@bot.command(name="lock")
@commands.has_permissions(manage_channels=True)
async def lock(ctx):
  overwrite = ctx.channel.overwrites_for(ctx.guild.default_role)
  overwrite.send_messages = False
  await ctx.channel.set_permissions(ctx.guild.default_role, overwrite=overwrite)
  await security_log(ctx.guild, "🔒 Channel Locked", f"**Channel:** {ctx.channel.mention}\n**Staff:** {ctx.author}")
  await ctx.send("🔒 Channel locked.")


@bot.command(name="unlock")
@commands.has_permissions(manage_channels=True)
async def unlock(ctx):
  overwrite = ctx.channel.overwrites_for(ctx.guild.default_role)
  overwrite.send_messages = None
  await ctx.channel.set_permissions(ctx.guild.default_role, overwrite=overwrite)
  await security_log(ctx.guild, "🔓 Channel Unlocked", f"**Channel:** {ctx.channel.mention}\n**Staff:** {ctx.author}", discord.Color.green())
  await ctx.send("🔓 Channel unlocked.")


@bot.command(name="nick")
async def nick(ctx, member: discord.Member, *, nickname: str = None):
  if not await check_staff(ctx) or not ctx.author.guild_permissions.manage_nicknames:
    await ctx.send("❌ You need the configured staff role and **Manage Nicknames** permission.", delete_after=5)
    return
  if not await can_moderate(ctx, member):
    return
  await member.edit(nick=nickname, reason=f"Changed by {ctx.author}: nickname moderation")
  await security_log(ctx.guild, "✏️ Nickname Changed", f"**User:** {member} (`{member.id}`)\n**Staff:** {ctx.author}\n**Nickname:** `{nickname or 'Reset'}`", discord.Color.blurple())
  await ctx.send(f"✏️ Nickname updated for {member.mention}.")


@bot.command(name="roleadd")
async def roleadd(ctx, member: discord.Member, role: discord.Role):
  if not await check_staff(ctx) or not ctx.author.guild_permissions.manage_roles:
    await ctx.send("❌ You need the configured staff role and **Manage Roles** permission.", delete_after=5)
    return
  if role >= ctx.guild.me.top_role:
    await ctx.send("❌ I cannot manage that role. Move my bot role higher.", delete_after=5)
    return
  if role >= ctx.author.top_role and ctx.author.id != ctx.guild.owner_id:
    await ctx.send("❌ You cannot manage a role equal to or higher than your highest role.", delete_after=5)
    return
  await member.add_roles(role, reason=f"Role added by {ctx.author}")
  await security_log(ctx.guild, "➕ Role Added", f"**User:** {member}\n**Role:** {role.mention}\n**Staff:** {ctx.author}", discord.Color.green())
  await ctx.send(f"➕ Added {role.mention} to {member.mention}.")


@bot.command(name="roleremove")
async def roleremove(ctx, member: discord.Member, role: discord.Role):
  if not await check_staff(ctx) or not ctx.author.guild_permissions.manage_roles:
    await ctx.send("❌ You need the configured staff role and **Manage Roles** permission.", delete_after=5)
    return
  if role >= ctx.guild.me.top_role:
    await ctx.send("❌ I cannot manage that role. Move my bot role higher.", delete_after=5)
    return
  if role >= ctx.author.top_role and ctx.author.id != ctx.guild.owner_id:
    await ctx.send("❌ You cannot manage that role.", delete_after=5)
    return
  await member.remove_roles(role, reason=f"Role removed by {ctx.author}")
  await security_log(ctx.guild, "➖ Role Removed", f"**User:** {member}\n**Role:** {role.mention}\n**Staff:** {ctx.author}", discord.Color.orange())
  await ctx.send(f"➖ Removed {role.mention} from {member.mention}.")


@bot.command(name="userinfo")
async def userinfo(ctx, member: discord.Member = None):
  member = member or ctx.author
  roles = [r.mention for r in member.roles[1:]][-15:]
  embed = discord.Embed(title=f"👤 User Info — {member}", color=discord.Color.blurple())
  embed.set_thumbnail(url=member.display_avatar.url)
  embed.add_field(name="ID", value=f"`{member.id}`", inline=False)
  embed.add_field(name="Joined", value=discord.utils.format_dt(member.joined_at, "R") if member.joined_at else "Unknown", inline=True)
  embed.add_field(name="Account Created", value=discord.utils.format_dt(member.created_at, "R"), inline=True)
  embed.add_field(name="Roles", value=" ".join(roles) if roles else "None", inline=False)
  await ctx.send(embed=embed)


@bot.command(name="serverinfo")
async def serverinfo(ctx):
  g = ctx.guild
  embed = discord.Embed(title=f"🏠 Server Info — {g.name}", color=discord.Color.blurple())
  embed.add_field(name="Owner", value=f"<@{g.owner_id}>" if g.owner_id else "Unknown", inline=True)
  embed.add_field(name="Members", value=str(g.member_count), inline=True)
  embed.add_field(name="Channels", value=str(len(g.channels)), inline=True)
  embed.add_field(name="Roles", value=str(len(g.roles)), inline=True)
  embed.add_field(name="Created", value=discord.utils.format_dt(g.created_at, "R"), inline=True)
  await ctx.send(embed=embed)

# --- Moderation & Purge Commands ---

@bot.command()
async def purge(ctx, amount: int):
  if not await check_senior(ctx):
    await ctx.send("You do not have permission to use this command. Only Senior Moderators can purge messages.", delete_after=5)
    return

  if not ctx.guild.me.guild_permissions.manage_messages:
    await ctx.send("❌ I need the **Manage Messages** permission to purge messages.", delete_after=5)
    return

  if amount < 1 or amount > 100:
    await ctx.send("Please specify a number between **1 and 100**.", delete_after=5)
    return

  try:
    await ctx.message.delete()
    deleted = await ctx.channel.purge(limit=amount)
    
    await ctx.send(f"Successfully deleted **{len(deleted)}** messages.", delete_after=5)

    log_embed = discord.Embed(title="Messages Purged", color=discord.Color.purple(), timestamp=discord.utils.utcnow())
    log_embed.add_field(name="Senior Mod", value=str(ctx.author), inline=False)
    log_embed.add_field(name="Channel", value=ctx.channel.mention, inline=True)
    log_embed.add_field(name="Count", value=str(len(deleted)), inline=True)
    await send_log(ctx.guild, log_embed)

  except Exception as e:
    await ctx.send(f"Failed to purge messages: {e}", delete_after=5)


@bot.command()
async def jail(ctx, member: discord.Member, *, reason: str = "No reason provided"):
  if not await check_staff(ctx):
    await ctx.send("You do not have permission to use this command.")
    return
  if not await can_moderate(ctx, member):
    return

  jail_role_id = get_config(ctx.guild.id, "jail_role")
  if not jail_role_id:
    await ctx.send("Jail role is not set! Use `>setjail @Role` first.")
    return

  jail_role = ctx.guild.get_role(int(jail_role_id))
  if not jail_role:
    await ctx.send("Configured jail role no longer exists.")
    return

  proof_url = ctx.message.attachments[0].url if ctx.message.attachments else None

  data = load_data()
  g_id_str = str(ctx.guild.id)
  u_id_str = str(member.id)

  if proof_url:
    if "temp_proof" not in data:
      data["temp_proof"] = {}
    data["temp_proof"][u_id_str] = proof_url

  if g_id_str not in data["jail_info"]:
    data["jail_info"][g_id_str] = {}
  data["jail_info"][g_id_str][u_id_str] = {"reason": reason, "staff": str(ctx.author)}
  save_data(data)

  try:
    await member.add_roles(jail_role, reason=reason)
    add_stat(ctx.guild.id, ctx.author.id, "jails")
  except Exception as e:
    await ctx.send(f"Failed to apply jail role: {e}")
    return

  try:
    dm_embed = discord.Embed(
        title=f"You have been jailed in {ctx.guild.name}",
        description=f"**Reason:** {reason}",
        color=discord.Color.red(),
    )
    view = AppealButtonView(ctx.guild.id)
    await member.send(embed=dm_embed, view=view)
  except discord.Forbidden:
    pass

  log_embed = discord.Embed(title="Member Jailed", color=discord.Color.red(), timestamp=discord.utils.utcnow())
  log_embed.add_field(name="User", value=f"{member} ({member.id})", inline=False)
  log_embed.add_field(name="Staff", value=str(ctx.author), inline=True)
  log_embed.add_field(name="Reason", value=reason, inline=True)
  if proof_url:
    log_embed.set_image(url=proof_url)
  await send_log(ctx.guild, log_embed)

  await ctx.send(f"Successfully jailed {member.mention}. User has been DM'd.")


@bot.command()
async def unjail(ctx, member: discord.Member):
  if not await check_staff(ctx):
    await ctx.send("You do not have permission to use this command.")
    return
  if not await can_moderate(ctx, member):
    return

  jail_role_id = get_config(ctx.guild.id, "jail_role")
  if not jail_role_id:
    await ctx.send("Jail role is not set!")
    return

  jail_role = ctx.guild.get_role(int(jail_role_id))
  if jail_role and jail_role in member.roles:
    await member.remove_roles(jail_role)
    
    log_embed = discord.Embed(title="Member Unjailed", color=discord.Color.blue(), timestamp=discord.utils.utcnow())
    log_embed.add_field(name="User", value=f"{member} ({member.id})", inline=False)
    log_embed.add_field(name="Staff", value=str(ctx.author), inline=False)
    await send_log(ctx.guild, log_embed)

    await ctx.send(f"Successfully unjailed {member.mention}.")
  else:
    await ctx.send("That member is not currently jailed.")


@bot.command()
async def warn(ctx, member: discord.Member, *, reason: str = "No reason provided"):
  if not await check_staff(ctx):
    await ctx.send("You do not have permission.")
    return
  if not await can_moderate(ctx, member):
    return

  add_stat(ctx.guild.id, ctx.author.id, "warns")
  add_warn(ctx.guild.id, member.id, reason, ctx.author)

  try:
    await member.send(f"You were warned in **{ctx.guild.name}** for: {reason}")
  except discord.Forbidden:
    pass

  log_embed = discord.Embed(title="Member Warned", color=discord.Color.yellow(), timestamp=discord.utils.utcnow())
  log_embed.add_field(name="User", value=f"{member} ({member.id})", inline=False)
  log_embed.add_field(name="Staff", value=str(ctx.author), inline=True)
  log_embed.add_field(name="Reason", value=reason, inline=True)
  await send_log(ctx.guild, log_embed)

  await ctx.send(f"Warned {member.mention} for: {reason}")


@bot.command(name="warns")
async def check_warns(ctx, member: discord.Member = None):
  if not await check_staff(ctx):
    await ctx.send("You do not have permission.")
    return

  target = member or ctx.author
  data = load_data()
  user_warns = data.get("warns", {}).get(str(ctx.guild.id), {}).get(str(target.id), [])

  embed = discord.Embed(
      title=f"Warnings for {target}",
      description=f"Total Warnings: **{len(user_warns)}**",
      color=discord.Color.yellow(),
  )

  if user_warns:
    for idx, w in enumerate(user_warns, 1):
      embed.add_field(
          name=f"Warning #{idx} (By: {w['staff']})",
          value=w["reason"],
          inline=False,
      )
  else:
    embed.add_field(name="Record", value="This user has no active warnings.", inline=False)

  await ctx.send(embed=embed)


@bot.command()
async def mute(ctx, member: discord.Member, *, reason: str = "No reason provided"):
  if not await check_staff(ctx) or not ctx.author.guild_permissions.moderate_members:
    await ctx.send("❌ You need the configured staff role and **Timeout Members** permission.", delete_after=5)
    return
  if not await can_moderate(ctx, member):
    return

  add_stat(ctx.guild.id, ctx.author.id, "mutes")
  duration = discord.utils.utcnow() + timedelta(minutes=10)
  try:
    await member.timeout(duration, reason=reason)
    await member.send(f"You were muted in **{ctx.guild.name}** for: {reason}")
  except Exception as e:
    await ctx.send(f"Failed to mute: {e}")
    return

  log_embed = discord.Embed(title="Member Muted", color=discord.Color.dark_orange(), timestamp=discord.utils.utcnow())
  log_embed.add_field(name="User", value=f"{member} ({member.id})", inline=False)
  log_embed.add_field(name="Staff", value=str(ctx.author), inline=True)
  log_embed.add_field(name="Reason", value=reason, inline=True)
  await send_log(ctx.guild, log_embed)

  await ctx.send(f"Muted {member.mention} for: {reason}")


@bot.command(name="ms")
async def modstats(ctx, member: discord.Member = None):
  target = member or ctx.author
  data = load_data()
  
  guild_stats = data.get("modstats", {}).get(str(ctx.guild.id), {})
  stats = guild_stats.get(str(target.id), {"jails": 0, "mutes": 0, "warns": 0, "bans": 0})

  embed = discord.Embed(title=f"Moderation Statistics for {target}", color=discord.Color.blue())
  embed.add_field(name="Jails Executed", value=stats.get("jails", 0), inline=True)
  embed.add_field(name="Mutes Executed", value=stats.get("mutes", 0), inline=True)
  embed.add_field(name="Warns Issued", value=stats.get("warns", 0), inline=True)
  embed.add_field(name="Bans Executed", value=stats.get("bans", 0), inline=True)
  await ctx.send(embed=embed)


# --- Leveling Event Handler + Strict Security ---
@bot.event
async def on_message(message):
  if not message.guild:
    await bot.process_commands(message)
    return

  # --- Automatic Reaction System ---
  # React only to normal user messages in the configured channel.
  if not message.author.bot:
    try:
      reaction_cfg = security_config(message.guild.id)
      reaction_channel_id = reaction_cfg.get("reaction_channel")
      reaction_emoji = reaction_cfg.get("reaction_emoji")
      if reaction_channel_id and reaction_emoji and message.channel.id == int(reaction_channel_id):
        await message.add_reaction(reaction_emoji)
    except (discord.Forbidden, discord.HTTPException, ValueError):
      pass

  # Security system runs before leveling and before command processing.
  if not message.author.bot:
    cfg = security_config(message.guild.id)
    if cfg.get("security_enabled", True) and not is_security_exempt(message.author):
      now = datetime.now(timezone.utc)
      key = (message.guild.id, message.author.id)

      # Anti-invite / anti-link protection.
      invite_pattern = re.compile(r"(?:https?://)?(?:www\.)?(?:discord\.gg|discord\.com/invite)/[^\s]+", re.I)
      url_pattern = re.compile(r"https?://[^\s]+", re.I)
      is_invite = bool(invite_pattern.search(message.content))
      is_link = bool(url_pattern.search(message.content))
      if (cfg.get("anti_invites", True) and is_invite) or (cfg.get("anti_links", True) and is_link):
        try:
          await message.delete()
        except (discord.Forbidden, discord.NotFound):
          pass
        await security_log(message.guild, "🚫 Blocked Link/Invite", f"**User:** {message.author.mention} (`{message.author.id}`)\n**Channel:** {message.channel.mention}\n**Content:** `{message.content[:500]}`")
        try:
          await message.channel.send(f"🚫 {message.author.mention}, links/invites are not allowed here.", delete_after=5)
        except Exception:
          pass
        await bot.process_commands(message)
        return

      # Anti-mass-mention.
      mention_count = len(message.mentions) + len(message.role_mentions)
      if cfg.get("anti_mass_mentions", True) and (mention_count >= 5 or message.mention_everyone):
        try:
          await message.delete()
        except (discord.Forbidden, discord.NotFound):
          pass
        await security_log(message.guild, "📢 Mass Mention Blocked", f"**User:** {message.author.mention}\n**Mentions:** `{mention_count}`")
        await bot.process_commands(message)
        return

      # Anti-caps spam.
      letters = [c for c in message.content if c.isalpha()]
      if cfg.get("anti_caps", True) and len(letters) >= 12:
        caps_ratio = sum(c.isupper() for c in letters) / len(letters)
        if caps_ratio >= 0.80:
          try:
            await message.delete()
          except (discord.Forbidden, discord.NotFound):
            pass
          await security_log(message.guild, "🔠 Excessive Caps Blocked", f"**User:** {message.author.mention}\n**Channel:** {message.channel.mention}")
          await bot.process_commands(message)
          return

      # Anti-spam: default is 5 messages in 8 seconds. Strict mode also times out the user.
      if cfg.get("anti_spam", True):
        dq = _message_tracker[message.guild.id][message.author.id]
        dq.append(now.timestamp())
        window = int(cfg.get("spam_window", 8))
        while dq and now.timestamp() - dq[0] > window:
          dq.popleft()
        if len(dq) >= int(cfg.get("spam_limit", 5)):
          try:
            await message.delete()
          except (discord.Forbidden, discord.NotFound):
            pass
          if cfg.get("strict_mode", True) and message.author.guild_permissions.moderate_members is False:
            try:
              await message.author.timeout(now + timedelta(minutes=10), reason="Automatic anti-spam protection")
            except Exception:
              pass
          await security_log(message.guild, "🚨 Spam Protection Triggered", f"**User:** {message.author.mention} (`{message.author.id}`)\n**Messages:** `{len(dq)}` in `{window}s`", discord.Color.orange())
          dq.clear()
          try:
            await message.channel.send(f"🛡️ {message.author.mention} was rate-limited for spam.", delete_after=5)
          except Exception:
            pass
          await bot.process_commands(message)
          return

      # Anti-duplicate messages.
      if cfg.get("anti_duplicate", True) and message.content.strip():
        dq = _duplicate_tracker[message.guild.id][message.author.id]
        dq.append((message.content.strip(), now.timestamp()))
        while dq and now.timestamp() - dq[0][1] > 12:
          dq.popleft()
        same_count = sum(1 for content, _ in dq if content == message.content.strip())
        if same_count >= int(cfg.get("duplicate_limit", 3)):
          try:
            await message.delete()
          except (discord.Forbidden, discord.NotFound):
            pass
          await security_log(message.guild, "🔁 Duplicate Spam Blocked", f"**User:** {message.author.mention}\n**Channel:** {message.channel.mention}")
          await bot.process_commands(message)
          return

  # Existing leveling system.
  if message.author.bot:
    await bot.process_commands(message)
    return

  guild_id = str(message.guild.id)
  user_id = str(message.author.id)

  data = load_data()
  if "user_xp" not in data:
    data["user_xp"] = {}
  if guild_id not in data["user_xp"]:
    data["user_xp"][guild_id] = {}

  user_data = data["user_xp"][guild_id].get(user_id, {"xp": 0, "level": 0})
  user_data["xp"] += random.randint(15, 25)
  next_level_xp = (user_data["level"] + 1) * 150

  if user_data["xp"] >= next_level_xp:
    user_data["level"] += 1
    new_level = user_data["level"]
    lvl_config = data.get("levels", {}).get(guild_id, {})
    notif_channel_id = lvl_config.get("channel_id")
    milestone_roles = lvl_config.get("roles", {}).get(str(new_level), [])

    if milestone_roles:
      member = message.guild.get_member(message.author.id)
      if member:
        for r_id in milestone_roles:
          role = message.guild.get_role(int(r_id))
          if role:
            try:
              await member.add_roles(role)
            except Exception:
              pass

    if notif_channel_id:
      channel = message.guild.get_channel(int(notif_channel_id))
      if channel:
        try:
          await channel.send(f"🎉 Congratulations {message.author.mention}! You leveled up to **Level {new_level}**!")
        except Exception:
          pass

  data["user_xp"][guild_id][user_id] = user_data
  save_data(data)
  await bot.process_commands(message)


@bot.event
async def on_member_join(member):
  if member.bot:
    cfg = security_config(member.guild.id)
    whitelist = cfg.get("security_whitelist", [])
    if cfg.get("security_enabled", True) and cfg.get("anti_bots", False) and member.id not in whitelist:
      try:
        await member.kick(reason="Strict Security: unapproved bot")
        await security_log(member.guild, "🤖 Unapproved Bot Removed", f"**Bot:** {member} (`{member.id}`) was removed because it was not whitelisted.")
      except Exception:
        pass
    return

  cfg = security_config(member.guild.id)
  if not cfg.get("security_enabled", True) or not cfg.get("anti_raid", True):
    return

  now = datetime.now(timezone.utc).timestamp()
  joins = _join_tracker[member.guild.id]
  joins.append(now)
  window = int(cfg.get("raid_window", 20))
  while joins and now - joins[0] > window:
    joins.popleft()

  if len(joins) >= int(cfg.get("raid_limit", 6)):
    account_age = (datetime.now(timezone.utc) - member.created_at).total_seconds()
    if account_age < 3 * 86400:
      try:
        await member.kick(reason="Strict Security: suspected raid account")
        await security_log(member.guild, "🚨 Raid Protection Triggered", f"Removed suspicious new account **{member}** (`{member.id}`).\n**Joins:** `{len(joins)}` in `{window}s`.")
      except Exception:
        pass


@bot.event
async def on_ready():
  if not check_giveaways.is_running():
    check_giveaways.start()
  try:
    await bot.tree.sync()
    print("Successfully synced application slash commands.")
  except Exception as e:
    print(f"Failed to sync slash commands: {e}")
  print(f"Logged in as {bot.user} (ID: {bot.user.id})")


# --- Command Error Handler ---
@bot.event
async def on_command_error(ctx, error):
  if isinstance(error, commands.CommandNotFound):
    return
  if isinstance(error, commands.MissingPermissions):
    await ctx.send("❌ You do not have the required Discord permissions.", delete_after=5)
    return
  if isinstance(error, commands.MissingRequiredArgument):
    await ctx.send(f"❌ Missing argument: `{error.param.name}`. Use `>help` for command usage.", delete_after=6)
    return
  if isinstance(error, commands.BadArgument):
    await ctx.send("❌ Invalid member, role, channel, or number. Check your command and try again.", delete_after=6)
    return
  if isinstance(error, commands.NoPrivateMessage):
    await ctx.send("❌ This command can only be used inside a server.", delete_after=5)
    return
  print(f"Command error in {ctx.command}: {error}")


# --- Execution Routine ---
if __name__ == "__main__":
  import threading

  t = threading.Thread(target=run_flask)
  t.daemon = True
  t.start()

  TOKEN = os.environ.get("DIS_TOKEN")
  if not TOKEN:
    raise ValueError("No DIS_TOKEN environment variable found. Please set your bot token in Render's Environment settings.")
  bot.run(TOKEN)
