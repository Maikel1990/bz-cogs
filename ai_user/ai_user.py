import json
import random

import discord
import openai
from redbot.core import Config, checks, commands

from ai_user.image import create_image_prompt
from ai_user.text import create_text_prompt


class AI_User(commands.Cog):
    whitelist = None

    def __init__(self, bot):
        self.bot = bot

        self.config = Config.get_conf(self, identifier=754070)

        default_global = {
            "scan_images": False,
            "reply_percent": 0.5,
        }

        default_guild = {
            "channels_whitelist": []
        }

        self.config.register_global(**default_global)
        self.config.register_guild(**default_guild)

    async def initalize_openai(self, message):
        openai.api_key = (await self.bot.get_shared_api_tokens("openai")).get("api_key")
        if not openai.api_key:
            return await message.channel.send("OpenAI API key not set. Please set it with `[p]set api openai api_key,API_KEY`")

    @commands.group()
    async def ai_user(self, _):
        pass

    @ai_user.command()
    async def config(self, message):
        """ Returns current config """
        embed = discord.Embed(title="AI User Settings")
        embed.add_field(name="Scan Images", value=await self.config.scan_images())
        embed.add_field(name="Reply Percent", value=await self.config.reply_percent() * 100)
        embed.add_field(name="Whitelisted Channels", value=await self.config.guild(message.guild).channels_whitelist())
        return await message.send(embed=embed)


    @ai_user.command()
    @checks.is_owner()
    async def scan_images(self, ctx):
        """ Toggle image scanning (req. cpu usage / tesseract)"""
        value = not await self.config.scan_images()
        await self.config.scan_images.set(value)
        embed = discord.Embed(title = "⚠️ CPU LOAD, REQUIRES TESSERACT INSTALL ⚠️")
        embed.add_field(name="Scanning Images now set to", value=value)
        return await ctx.send(embed=embed)

    @ai_user.command()
    @checks.is_owner()
    async def percent(self, ctx, new_value):
        """ Chance the bot will reply to a message """
        try:
            new_value = float(new_value)
        except ValueError:
            return await ctx.send("Value must be number")
        await self.config.reply_percent.set(new_value / 100)
        embed = discord.Embed(title="The chance that bot will reply is now set to")
        embed.add_field(name="", value=new_value)
        return await ctx.send(embed=embed)

    @ai_user.command()
    @checks.admin_or_permissions(manage_guild=True)
    async def add(self, ctx, new_value):
        """Add a channel to the whitelist to allow the bot to reply in """
        new_whitelist = (await self.config.guild(ctx.guild).channels_whitelist())
        try:
            new_value = int(new_value)
        except ValueError:
            return await ctx.send("Value must be a channel id")
        new_whitelist.append(new_value)
        await self.config.guild(ctx.guild).channels_whitelist.set(new_whitelist)
        self.whitelist = await self.config.guild(ctx.guild).channels_whitelist()
        embed = discord.Embed(title="The whitelist is now")
        embed.add_field(name="", value=self.whitelist)
        return await ctx.send(embed=embed)

    @ai_user.command()
    @checks.admin_or_permissions(manage_guild=True)
    async def remove(self, ctx, new_value):
        """Remove a channel from the whitelist """
        new_whitelist = (await self.config.guild(ctx.guild).channels_whitelist())
        new_whitelist.remove(int(new_value))
        await self.config.guild(ctx.guild).channels_whitelist.set(new_whitelist)
        self.whitelist = new_whitelist
        embed = discord.Embed(title="The whitelist is now")
        embed.add_field(name="", value=self.whitelist)
        return await ctx.send(embed=embed)

    @commands.guild_only()
    @commands.Cog.listener()
    async def on_message_without_command(self, message: discord.Message):
        if self.whitelist is None:
            self.whitelist = await self.config.guild(message.guild).channels_whitelist()

        if (message.channel.id not in self.whitelist) or message.author.bot:
            return
        percent = await self.config.reply_percent()
        if random.random() > percent:
            return

        prompt = None
        if (message.attachments and message.attachments[0] and await self.config.scan_images()):
            prompt = await create_image_prompt(message)
        else:

            prompt = create_text_prompt(message)
            if prompt is None:
                return
            prompt[1:1] = await (self.get_history(message))


        if prompt is None:
            return


        return await self.sent_reply(message, prompt)

    async def sent_reply(self, message, prompt : list[dict]):
        """ Generates the reply using OpenAI and sends the result """

        def check_moderated_response(response):
            """ filters out responses that were moderated out """
            response = response.lower()
            filters = ["language model", "openai", "sorry", "please"]

            for filter in filters:
                if filter in response:
                    return True

            return False

        if not openai.api_key:
            await self.initalize_openai(message)

        async with message.channel.typing():
            print(json.dumps(prompt, indent=4))
            response = openai.ChatCompletion.create(
                model="gpt-3.5-turbo",
                messages=prompt,
            )

            try:
                reply = response["choices"][0]["message"]["content"]
            except:
                print("Bad response from OpenAI:")
                print(response)
                print()
                return

            if check_moderated_response(reply):
                return

            await message.channel.send(reply)

    async def get_history(self, message: discord.Message, limit=10):
        """ Returns a history of messages """

        def is_bad_message(message: discord.Message):
            """ Returns True when message has attachments or long msg """
            if (len(message.attachments) > 1):
                return True
            words = message.content.split(" ")
            if len(words) > 300:
                return True

        history = await message.channel.history(limit=limit, before=message).flatten()
        history.reverse()

        messages = []

        i = 0
        while (i < len(history)):
            if i > 0 and (history[i].created_at - history[i - 1].created_at).total_seconds() > 1188: # 20 minutes
                break
            if history[i].author.id == self.bot.user.id:
                messages.append(
                    {"role": "assistant", "content": history[i].content})
                i += 1
                continue
            elif (is_bad_message(history[i])):
                break
            else:
                messages.append(
                    {"role": "user", "content": history[i].author.name + ":  " + history[i].content})
            i += 1

        return messages