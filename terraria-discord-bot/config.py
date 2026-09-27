"""Configuração local; nenhum segredo é impresso."""
import os
from pathlib import Path

from dotenv import load_dotenv

BASE = Path(__file__).resolve().parent


class Config:
    def __init__(self):
        load_dotenv(BASE / '.env')
        self.token = os.getenv('DISCORD_TOKEN', '').strip()
        self.guild_id = self.number('DISCORD_GUILD_ID', 0)
        self.channel_id = self.number('DISCORD_CHANNEL_ID', 0)
        self.admin_id = self.number('DISCORD_ADMIN_ID', 0)
        self.role_id = self.number('DISCORD_ADMIN_ROLE_ID', 0)
        self.host = os.getenv('TERRARIA_HOST', '127.0.0.1').strip()
        self.public_host = os.getenv('TERRARIA_PUBLIC_HOST', '').strip() or 'Oculto'
        self.port = self.number('TERRARIA_PORT', 7777, 1, 65535)
        self.interval = self.number('POLL_SECONDS', 10, 2, 300)
        self.mode = os.getenv('TERRARIA_MODE', 'tcp').strip().lower()
        if self.mode not in ('tcp', 'process'):
            raise ValueError('TERRARIA_MODE deve ser tcp ou process')
        self.binary = self.path('TERRARIA_EXECUTABLE')
        self.server_config = self.path('TERRARIA_CONFIG')
        self.server_values = {}
        if self.mode == 'process':
            if not self.binary.is_file() or not self.server_config.is_file():
                raise ValueError('Configure TERRARIA_EXECUTABLE e TERRARIA_CONFIG com arquivos existentes')
            for line in self.server_config.read_text(encoding='utf-8-sig').splitlines():
                if '=' in line and not line.lstrip().startswith('#'):
                    key, value = line.split('=', 1)
                    self.server_values[key.strip().lower()] = value.strip()
            if not self.server_values.get('world'):
                raise ValueError('serverconfig.txt precisa de world= para iniciar sem menu interativo')
            if self.server_values.get('language') != 'en-US':
                raise ValueError('Use language=en-US no serverconfig.txt para reconhecer o console')
        self.secrets = tuple(value for value in (
            self.token, os.getenv('TERRARIA_PASSWORD', ''),
            self.server_values.get('password', ''),
        ) if value)

    @staticmethod
    def number(key, default, minimum=0, maximum=2**64 - 1):
        try:
            value = int(os.getenv(key, '') or default)
        except ValueError:
            raise ValueError(f'{key} deve ser um inteiro') from None
        if not minimum <= value <= maximum:
            raise ValueError(f'{key} fora do intervalo permitido')
        return value

    @staticmethod
    def path(key):
        return (BASE / os.getenv(key, '')).resolve()

    def validate_discord(self):
        if not self.token or not self.guild_id or not self.channel_id:
            raise ValueError('Preencha DISCORD_TOKEN, DISCORD_GUILD_ID e DISCORD_CHANNEL_ID no .env local')
