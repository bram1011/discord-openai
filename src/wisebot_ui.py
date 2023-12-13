import discord
from discord import ui
import random
from discord.interactions import Interaction
import pytz
from config import log

EASTERN_TIMEZONE = pytz.timezone("US/Eastern")


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


class TeamsSubmit(ui.Button):
    member_dropdown: ui.UserSelect
    voice_channels_dropdown: ui.ChannelSelect

    async def callback(self, interaction: Interaction):
        try:
            self.view.stop()
            members = self.member_dropdown.values
            voice_channels = self.voice_channels_dropdown.values
            num_teams = len(voice_channels)
            await interaction.response.send_message(
                f"Creating {num_teams} teams and moving players to their channels"
            )
            if num_teams > len(members):
                await interaction.followup.send(
                    f"Cannot create {num_teams} teams with only {len(members)} players",
                )
                return
            random.shuffle(members)
            random.shuffle(voice_channels)
            channel_index = 0
            for member in members:
                if member.voice is None or member.voice.channel is None:
                    await interaction.followup.send(
                        f"Cannot move {member.display_name} because they are not in a voice channel"
                    )
                    continue
                await member.move_to(voice_channels[channel_index])
                channel_index = (channel_index + 1) % num_teams
            await interaction.followup.send(
                f"Created {num_teams} teams with {len(members)} total players"
            )
        except Exception as e:
            log.exception("Could not create teams")
            await interaction.followup.send(f"Could not create teams due to error")


class PlayersDropdown(ui.UserSelect):
    def __init__(self):
        super().__init__(
            placeholder="Select players to split into teams",
            min_values=2,
            max_values=25,
        )

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)


class TeamsChannelsDropdown(ui.ChannelSelect):
    def __init__(self):
        super().__init__(
            placeholder="Select voice channels to split players into",
            min_values=2,
            max_values=10,
            channel_types=[discord.ChannelType.voice],
        )

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)


class TeamsView(ui.View):
    players_dropdown = PlayersDropdown()
    channels_dropdown = TeamsChannelsDropdown()
    submit_button = TeamsSubmit(
        style=discord.ButtonStyle.primary, label="Shuffle teams"
    )
    submit_button.member_dropdown = players_dropdown
    submit_button.voice_channels_dropdown = channels_dropdown

    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(self.players_dropdown)
        self.add_item(self.channels_dropdown)
        self.add_item(self.submit_button)
