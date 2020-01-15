
from evennia.utils.ansi import ANSIString

from athanor.gamedb.scripts import AthanorOptionScript
from athanor.gamedb.models import ThemeBridge, ThemeParticipant


class AthanorTheme(AthanorOptionScript):
    re_name = re.compile(r"")

    def create_bridge(self, key, clean_key):
        if hasattr(self, 'theme_bridge'):
            return
        ThemeBridge.objects.create(db_script=self, db_name=clean_key, db_iname=clean_key.lower(), db_cname=key)

    @classmethod
    def create_theme(cls, name, description, **kwargs):
        key = ANSIString(name)
        clean_key = str(key.clean())
        if '|' in clean_key:
            raise ValueError("Malformed ANSI in Theme Name.")
        if ThemeBridge.objects.filter(db_iname=clean_key.lower()).count():
            raise ValueError("Name conflicts with another Theme.")
        obj, errors = cls.create(clean_key, **kwargs)
        if obj:
            obj.create_bridge(key, clean_key)
            obj.db.desc = description
        else:
            raise ValueError(errors)
        return obj

    def add_character(self, character, list_type):
        return ThemeParticipant.objects.create(db_theme=self.theme_bridge, db_object=character, db_list_type=list_type)

    def remove_character(self, character):
        if (participant := self.participants.filter(db_object=character).first()):
            if character.db._primary_theme == participant:
                del character.db._primary_theme
            participant.delete()

    def __str__(self):
        return self.db_key

    def rename(self, key):
        key = ANSIString(key)
        clean_key = str(key.clean())
        if '|' in clean_key:
            raise ValueError("Malformed ANSI in Theme Name.")
        bridge = self.theme_bridge
        if ThemeBridge.objects.filter(db_iname=clean_key.lower()).exclude(id=bridge).count():
            raise ValueError("Name conflicts with another Theme.")
        self.key = clean_key
        bridge.db_name = clean_key
        bridge.db_iname = clean_key.lower()
        bridge.db_cname = key
