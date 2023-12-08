import discord
from discord import ui
from discord.ext import tasks
import logging
import colorlog
import pytz
from datetime import datetime, timedelta, time
from config import settings

TEST_GUILD = discord.Object(731728721588781057)

PLIK_URL = "http://192.168.0.229:7080"


class WiseBot(discord.AutoShardedClient):
    def __init__(self, *, intents: discord.Intents):
        super().__init__(
            intents=intents, shard_count=settings.bot.shards, heartbeat_timeout=60
        )
        self.tree = discord.app_commands.CommandTree(self)

    async def setup_hook(self):
        await self.tree.sync(guild=TEST_GUILD)
        await self.tree.sync(guild=None)
        self.tree.copy_global_to(guild=TEST_GUILD)
        check_events_today.start()
        check_events_within_one_hour.start()


class UserInvitesDropdown(ui.UserSelect):
    def __init__(self):
        super().__init__(
            placeholder="Select users to invite", min_values=1, max_values=25
        )

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)


class EventDropdown(ui.Select):
    def __init__(self, options: list[discord.SelectOption]):
        super().__init__(
            placeholder="Select an event", min_values=1, max_values=1, options=options
        )

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)


class EventInviteView(ui.View):
    def __init__(
        self,
        event_select: EventDropdown,
        user_select: UserInvitesDropdown,
        user: discord.User,
        initial_interaction: discord.Interaction,
        events: list[discord.ScheduledEvent],
    ):
        super().__init__(timeout=None)
        self.user = user
        self.initial_interaction = initial_interaction
        self.events = events
        self.add_item(event_select)
        self.add_item(user_select)
        self.add_item(SubmitInvitesButton(event_select, user_select, self))

    async def interaction_check(self, interaction: discord.Interaction):
        if interaction.user != self.user:
            await interaction.response.send_message(
                f"Only {self.user.display_name} can use this view", ephemeral=True
            )
        return interaction.user == self.user


class SubmitInvitesButton(ui.Button):
    def __init__(
        self,
        event_select: EventDropdown,
        user_select: UserInvitesDropdown,
        invite_view: EventInviteView,
    ):
        super().__init__(label="Submit", style=discord.ButtonStyle.primary)
        self.event_select = event_select
        self.user_select = user_select
        self.invite_view = invite_view

    async def callback(self, interaction: discord.Interaction):
        self.invite_view.stop()
        await interaction.response.send_message(
            f"Sending invites to {len(self.user_select.values)} users!", ephemeral=True
        )
        await self.invite_view.initial_interaction.delete_original_response()
        event: discord.ScheduledEvent = None
        try:
            for guild_event in self.invite_view.events:
                if guild_event.id == int(self.event_select.values[0]):
                    event = guild_event
            for user in self.user_select.values:
                log.info(f"Inviting {user} to {event}")
                await user.send(
                    embed=build_event_embed(
                        event,
                        f"{interaction.user.display_name} has invited you to {event.name}!",
                    )
                )
        except Exception as e:
            log.exception("Could not send invites for event {event.id}")
            await interaction.followup.send(
                f"Could not send invites for {event.name} due to error", ephemeral=True
            )


EASTERN_TIMEZONE = pytz.timezone("US/Eastern")

LOG_LEVEL = logging.getLevelNamesMapping()[settings.log.level]

log_handler = colorlog.StreamHandler()
log_handler.setFormatter(
    colorlog.ColoredFormatter(
        "%(log_color)s%(asctime)s %(name)s[%(funcName)s] - %(levelname)s: %(message)s"
    )
)

log = colorlog.getLogger("WiseBot")
log.addHandler(log_handler)
log.setLevel(LOG_LEVEL)
colorlog.getLogger().setLevel(logging.DEBUG)
colorlog.getLogger("discord").addHandler(log_handler)
colorlog.getLogger("discord").setLevel(logging.INFO)
log.info("Starting WiseBot")


discordPyIntents = discord.Intents.all()
client = WiseBot(intents=discordPyIntents)


@client.event
async def on_ready():
    log.info("WiseBot is ready")


@client.event
async def on_disconnect():
    log.warning("WiseBot is disconnected")


@client.tree.command(
    name="status", description="Get WiseBot's status", guild=TEST_GUILD
)
async def status(interaction: discord.Interaction):
    log.info(f"Received command to get status from {interaction.user}")
    status_embed: discord.Embed = discord.Embed(title="WiseBot Status")
    status_embed.add_field(
        name="Latency", value=client.latencies, inline=False
    ).add_field(name="Guilds", value=client.guilds, inline=False).add_field(
        name="Gateway", value=client.ws, inline=False
    ).add_field(
        name="Shards", value=client.shards, inline=False
    )
    await interaction.response.send_message(embed=status_embed, ephemeral=True)


@client.tree.command(
    name="sync", description="Sync WiseBot's commands", guild=TEST_GUILD
)
async def sync(interaction: discord.Interaction):
    log.info(f"Received command to sync WiseBot from {interaction.user}")
    if not interaction.user.guild_permissions.administrator:
        interaction.response.send_message(
            "You must be an administrator to sync WiseBot", ephemeral=True
        )
        return
    await client.tree.sync(guild=None)
    await interaction.response.send_message(
        "Synced WiseBot with Discord", ephemeral=True
    )


@client.tree.command(name="invite", description="Invite Users to an Event")
async def invite(interaction: discord.Interaction):
    log.info(f"Received command to invite a user from {interaction.user}")
    event_select: list[discord.SelectOption] = []
    events = interaction.guild.scheduled_events
    if len(events) == 0:
        await interaction.followup.send(content="No events found", ephemeral=True)
        return
    for event in events:
        if event.status is discord.EventStatus.scheduled:
            event_select.append(
                discord.SelectOption(
                    label=event.name, description=event.description, value=event.id
                )
            )
    await interaction.response.send_message(
        content="Select an event and users to invite",
        view=EventInviteView(
            EventDropdown(event_select),
            UserInvitesDropdown(),
            interaction.user,
            interaction,
            events,
        ),
        ephemeral=True,
    )


def build_event_embed(event: discord.ScheduledEvent, title: str):
    embed: discord.Embed = discord.Embed(
        title=title,
        description=event.description,
        timestamp=event.start_time.astimezone(EASTERN_TIMEZONE),
        color=discord.Color.red(),
    )
    if event.channel is not None:
        embed.add_field(name="Channel", value=event.channel.jump_url, inline=False)
    if event.cover_image is not None:
        embed.set_image(url=event.cover_image.url)
    if event.location is not None:
        embed.add_field(name="Location", value=event.location, inline=False)
    if event.description is not None and len(event.description) > 0:
        embed.add_field(name="Description", value=event.description, inline=False)
    embed.add_field(name="Attendees", value=event.user_count, inline=False)
    embed.add_field(name="Event Details", value=event.url, inline=False)
    embed.add_field(name="Server", value=event.guild.name, inline=False)
    embed.set_author(name=event.creator.display_name, icon_url=event.creator.avatar.url)
    return embed


async def notify_event_subscribers(event: discord.ScheduledEvent, title: str):
    if event.user_count is None or event.user_count == 0:
        log.info(f"No users to notify for scheduled event {event.id}")
        return
    embed: discord.Embed = build_event_embed(event, title)
    users = event.users()
    async for user in users:
        log.info(f"Notifying user {user}")
        delete_time: datetime = event.start_time + timedelta(minutes=90)
        await user.send(
            embed=embed,
            delete_after=(
                delete_time - datetime.now(delete_time.tzinfo)
            ).total_seconds(),
            content=event.url,
        )


@client.event
async def on_scheduled_event_create(event: discord.ScheduledEvent):
    log.info(f"Scheduled event created: {event.id}")
    await event.guild.system_channel.send(
        embed=build_event_embed(event, f"Event {event.name} has been created!")
    )


@client.event
async def on_scheduled_event_update(
    before: discord.ScheduledEvent, after: discord.ScheduledEvent
):
    log.info(f"Scheduled event updated: {before.id}")
    event: discord.ScheduledEvent = await before.guild.fetch_scheduled_event(before.id)
    if (
        before.status is not discord.EventStatus.active
        and after.status is discord.EventStatus.active
    ):
        log.info(f"Scheduled event {before.id} is now active, notifying users")
        await notify_event_subscribers(event, f"Event {event.name} is starting now!")
        return
    if (
        before.start_time is not after.start_time
        and after.status is discord.EventStatus.scheduled
    ):
        log.info(f"Scheduled event {before.id} start time changed, notifying users")
        await notify_event_subscribers(
            event,
            f'Event {event.name}\'s start time has changed to {after.start_time.astimezone(EASTERN_TIMEZONE).strftime("%B %d, %Y at %I:%M %p %Z")}',
        )
    if (before.location is not after.location) or (before.channel is not after.channel):
        log.info(
            f"Scheduled event {before.id} location or channel changed, notifying users"
        )
        await notify_event_subscribers(
            event, f"Event {event.name}'s location or channel has changed"
        )


@tasks.loop(time=time(hour=9, tzinfo=EASTERN_TIMEZONE))
async def check_events_today():
    async for guild in client.fetch_guilds():
        log.info(f"Checking scheduled events for guild {guild.name}({guild.id})")
        for event in await guild.fetch_scheduled_events(with_counts=True):
            if event.start_time - datetime.now(event.start_time.tzinfo) <= timedelta(
                hours=24
            ):
                log.info(
                    f"Event {event.id} is scheduled to start today, notifying users"
                )
                await notify_event_subscribers(
                    event,
                    f"{event.name} is scheduled to start within the next 24 hours",
                )


@tasks.loop(minutes=60)
async def check_events_within_one_hour():
    # Check for events that are within one hour of starting
    async for guild in client.fetch_guilds():
        log.info(f"Checking scheduled events for guild {guild.name}({guild.id})")
        for event in await guild.fetch_scheduled_events(with_counts=True):
            if event.start_time - datetime.now(event.start_time.tzinfo) <= timedelta(
                minutes=60
            ):
                log.info(
                    f"Event {event.id} is scheduled to start within one hour, notifying users"
                )
                await notify_event_subscribers(
                    event, f"{event.name} is scheduled to start within the hour"
                )


client.run(token=settings.discord_secret, log_handler=None)
