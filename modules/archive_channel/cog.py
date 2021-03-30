import discord
from discord.ext import commands
from dotenv.main import load_dotenv
import constants
import os
import shutil
import zipfile
from utils import discord_utils
from modules.archive_channel import archive_constants
load_dotenv(override=True)


# TODO: This code's gonna need some refactoring. We should be able to save a lot of space, since most of the commands
# Use a lot of the same code. Also, archiving is super slow.
class ArchiveChannelCog(commands.Cog, name="Archive Channel"):
    """Downloads a channel's history and sends it as a file to the user"""
    def __init__(self, bot):
        self.bot = bot
        self.compression = zipfile.ZIP_DEFLATED

        self.reset_archive_dir()

    # TODO: While we're going through messages, it would be nice to see if we've already hit the 8MB limit somehow?
    # That would speed up the archiving of categories and servers by a lot. I guess it would be hard since we aren't
    # Compressing in real-time. We could try, though.
    async def archive_one_channel(self, channel):
        """Download a channel's history"""
        # Write the chat log. Replace attachments with their filename (for easy reference)
        text_log_path = os.path.join(archive_constants.ARCHIVE, channel.name + '_' + archive_constants.TEXT_LOG_PATH)
        with open(text_log_path, 'w') as f:
            async for msg in channel.history(limit=None, oldest_first=True):
                #print(f"{msg.created_at} - {msg.author.display_name.rjust(25, ' ')}: {msg.clean_content}")
                f.write(f"[ {msg.created_at.strftime('%m-%d-%Y, %H:%M:%S')} ] "
                        f"{msg.author.display_name.rjust(25, ' ')}: "
                        f"{msg.clean_content}")
                # Save attachments TODO is this necessary? Might waste space
                for attachment in msg.attachments:
                    f.write(f" {attachment.filename}")
                    # change duplicate filenames
                    # img.png would become img (1).png
                    original_path = os.path.join(archive_constants.ARCHIVE, archive_constants.IMAGES, attachment.filename)
                    proposed_path = original_path
                    dupe_counter = 1
                    while os.path.exists(proposed_path):
                        proposed_path = original_path.split('.')[0] + f" ({dupe_counter})." + original_path.split('.')[1]
                        dupe_counter += 1
                    await attachment.save(proposed_path)
                # Important: Write the newline after each comment is done
                f.write("\n")
            text_file_size = f.tell()

        ZIP_FILENAME = os.path.join(archive_constants.ARCHIVE, channel.name + '_archive.zip')
        # Create a zipfile and then walk through all the saved chatlogs and images, and zip em up
        with zipfile.ZipFile(ZIP_FILENAME, mode='w') as zf:
            for root, directories, files in os.walk(archive_constants.ARCHIVE):
                for filename in files:
                    if filename == ZIP_FILENAME.split('/')[-1]: # Don't include self
                        continue
                    zf.write(os.path.join(root, filename), compress_type=self.compression)
            zf_file_size = zf.fp.tell()
        # TODO: It may often be the case that we will be above 8MB (max filesize).
        # In that case, we just need to send the textfile
        return discord.File(ZIP_FILENAME), zf_file_size, discord.File(text_log_path), text_file_size


    def get_file_and_embed(self, channel, filesize_limit, zipfile, zipfile_size, textfile, textfile_size):
        """Check if zipfile and textfile can be sent or not, create embed with message"""
        embed = discord_utils.create_embed()
        if zipfile_size > filesize_limit:
            if textfile_size > filesize_limit:
                embed.add_field(name="ERROR: History Too Big",
                                value=f"Sorry about that! The chat log in {channel.mention} is too big for me to send.\n"
                                      f"The max file size I can send in this server is "
                                      f"`{(filesize_limit/archive_constants.BYTES_TO_MEGABYTES):.2f}MB`, but the chat log is "
                                      f"`{(textfile_size/archive_constants.BYTES_TO_MEGABYTES):.2f}MB`",
                                inline=False)
                file = None
            else:
                embed.add_field(name="WARNING: Attachments Too Big",
                                value=f"There are too many photos in {channel.mention} for me to send. The max file size "
                                      f"I can send in this server is "
                                      f"`{(filesize_limit/archive_constants.BYTES_TO_MEGABYTES):.2f}MB` but the zip is "
                                      f"`{(zipfile_size/archive_constants.BYTES_TO_MEGABYTES):.2f}MB`. I'll only be able to send you the chat log.",
                                inline=False)
                file = textfile
        else:
            file = zipfile
            embed = None
        return file, embed

    @commands.command(name="archivechannel")
    @commands.has_role(constants.BOT_WHISPERER)
    async def archivechannel(self, ctx, *args):
        """Command to download channel's history"""
        # TODO: Need error handling for asking a channel we don't have access to or invalid channel name
        print("Received archivechannel")
        self.reset_archive_dir()
        # Check if the user supplied a channel
        if len(args) < 1:
            # No arguments provided
            await ctx.send(embed=discord_utils.create_no_argument_embed('channel'))
            return
        # TODO: check discord docs for id=args[0] possibility?
        try:
            channel = self.find_channel(ctx.guild.channels, ' '.join(args))
        except ValueError:
            embed = discord_utils.create_embed()
            embed.add_field(name="ERROR: Cannot find channel",
                            value=f"Sorry, I cannot find a channel with name {' '.join(args)}",
                            inline=False)
            await ctx.send(embed=embed)
            return
        if not channel.type == 'text':
            embed = discord_utils.create_embed()
            embed.add_field(name="ERROR: Cannot archive non-text channels",
                            value=f"Sorry! I can only archive text channels, but "
                                  f"{channel} is a {channel.type} channel.",
                            inline=False)
            await ctx.send(embed=embed)
            return
        # If we've gotten to this point, we know we have a channel so we should probably let the user know.
        start_embed = self.get_start_embed(channel)
        await ctx.send(embed=start_embed)
        try:
            # zipfile, textfile
            zipfile, zipfile_size, textfile, textfile_size = await self.archive_one_channel(channel)
        except discord.errors.Forbidden:
            embed = discord_utils.create_embed()
            embed.add_field(name="ERROR: No access",
                            value=f"Sorry! I don't have access to {channel}. You'll need "
                                   f"to give me permission to view the channel if you want "
                                   f"to archive it",
                            inline=False)
            await ctx.send(embed=embed)
            return
        file, embed = self.get_file_and_embed(channel,
                                              ctx.guild.filesize_limit,
                                              zipfile,
                                              zipfile_size,
                                              textfile,
                                              textfile_size)
        await ctx.send(file=file, embed=embed)

    @commands.command(name="archivecategory")
    @commands.has_guild_permissions(administrator=True)
    async def archivecategory(self, ctx, *args):
        """Command to download the history of every text channel in the category"""
        print("Received archivecategory")
        # Check if the user supplied a channel
        if len(args) < 1:
            # No arguments provided
            await ctx.send(embed=discord_utils.create_no_argument_embed('category'))
            return

        try:
            category = self.find_channel(ctx.guild.channels, ' '.join(args))
        except ValueError:
            embed = discord_utils.create_embed()
            embed.add_field(name="ERROR: Cannot find category",
                            value=f"Sorry, I cannot find a category with name {' '.join(args)}",
                            inline=False)
            await ctx.send(embed=embed)
            return

        start_embed = self.get_start_embed(category)
        await ctx.send(embed=start_embed)
        for text_channel in category.text_channels:
            self.reset_archive_dir()
            try:
                zipfile, zipfile_size, textfile, textfile_size = await self.archive_one_channel(text_channel)
                file, embed = self.get_file_and_embed(text_channel,
                                                      ctx.guild.filesize_limit,
                                                      zipfile,
                                                      zipfile_size,
                                                      textfile,
                                                      textfile_size)
                await ctx.send(file=file, embed=embed)
            except discord.errors.Forbidden:
                embed = discord_utils.create_embed()
                embed.add_field(name="ERROR: No access",
                                value=f"Sorry! I don't have access to {text_channel.mention}. You'll need "
                                      f"to give me permission to view the channel if you want "
                                      f"to archive it",
                                inline=False)
                await ctx.send(embed=embed)
                continue

    # TODO: This code is mostly copy/pasted from archivecategory
    @commands.command(name="archiveserver")
    @commands.has_guild_permissions(administrator=True)
    async def archiveserver(self, ctx):
        """Command to archive every text channel in the server.

        WARNING: This command will take *very* long on any reasonably aged server"""
        print("Received archiveserver")
        start_embed = self.get_start_embed(ctx.guild)
        await ctx.send(embed=start_embed)

        for text_channel in ctx.guild.text_channels:
            self.reset_archive_dir()
            try:
                zipfile, zipfile_size, textfile, textfile_size = await self.archive_one_channel(text_channel)
                file, embed = self.get_file_and_embed(text_channel,
                                                      ctx.guild.filesize_limit,
                                                      zipfile,
                                                      zipfile_size,
                                                      textfile,
                                                      textfile_size)
                await ctx.send(file=file, embed=embed)
            except discord.errors.Forbidden:
                embed = discord_utils.create_embed()
                embed.add_field(name="ERROR: No access",
                                value=f"Sorry! I don't have access to {text_channel.mention}. You'll need "
                                      f"to give me permission to view the channel if you want "
                                      f"to archive it",
                                inline=False)
                await ctx.send(embed=embed)
                continue

    def find_channel(self, channels, channel_name):
        channel = discord.utils.get(channels, name=channel_name)

        if channel is None:
            channel_id = int(channel_name.replace('>', '').replace('<#', ''))
            channel = self.bot.get_channel(channel_id)
        return channel

    def get_start_embed(self, channel_or_guild):
        embed = discord_utils.create_embed()
        embed.add_field(name="Archive Started",
                        value=f"Your archiving of {channel_or_guild.mention if hasattr(channel_or_guild, 'mention') else channel_or_guild}"
                              f" has begun! This may take a while. If I run into "
                              f"any errors, I'll let you know.",
                        inline=False)
        embed.add_field(name="Problems?",
                        value="Taking too long? Let `@kevslinger` know",
                        inline=False)
        return embed

    def reset_archive_dir(self):
        # Remove the archive directory and remake
        if os.path.exists(archive_constants.ARCHIVE):
            shutil.rmtree(archive_constants.ARCHIVE)
        os.mkdir(archive_constants.ARCHIVE)
        os.mkdir(os.path.join(archive_constants.ARCHIVE, archive_constants.IMAGES))


def setup(bot):
    bot.add_cog(ArchiveChannelCog(bot))