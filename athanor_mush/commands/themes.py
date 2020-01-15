from evennia import GLOBAL_SCRIPTS
from athanor.commands.command import AthanorCommand


class CmdTheme(AthanorCommand):
    """
    The Theme System tracks played characters belonging to themes in this game.

    Usage:
        @theme
            Display all themes.
        @theme <theme name>
            Display details of a given theme.
        @theme <theme name>/<note name>
            Display theme note contents.
    """
    key = "@theme"
    aliases = ["@fclist", '@themes', '@cast']
    locks = "cmd:all()"
    help_category = "Characters"
    player_switches = []
    admin_switches = ['create', 'rename', 'delete', 'assign', 'remove', 'describe', 'status', 'type', 'note']
    system_name = 'THEME'


    admin_help = """
    |cStaff Commands|n
    
    @theme/create <theme name>=<description>
        Create a new theme.
        
    @theme/rename <theme name>=<new name>
        Rename a theme.
    
    @theme/delete <theme name>=<same name>
        Deletes a theme. Must provide the exact name twice to verify.
        DO NOT use this carelessly.
    
    @theme/assign <theme name>=<character>,<list type>
        Adds a character to a theme. Characters may belong to more than one theme as different list types.
        List types: FC, OC, OFC, etc. It'll take anything, but be consistent.
    
    @theme/status <character>=<new status>
        Set a character's status, such as Open, Closing, Played, Dead, etc.
    
    @theme/type <theme>=<character>,<new list type>
        Change a character's list type.
    
    @theme/primary <character>=<theme>
        Change a character's primary theme. This affects @finger displays.
    
    @theme/note <theme>/<note>=<contents>
        Add/replacing a theme note that players can read. Usually used for extra details attached to a theme
        such as adaptation details. Not case sensitive. Remove a note by setting it to #DELETE.
    """

    def switch_create(self):
        GLOBAL_SCRIPTS.theme.create_theme(self.session, self.lhs, self.rhs)

    def switch_rename(self):
        GLOBAL_SCRIPTS.theme.rename_theme(self.session, self.lhs, self.rhs)

    def switch_delete(self):
        GLOBAL_SCRIPTS.theme.delete_theme(self.session, self.lhs, self.rhs)

    def switch_main(self):
        themes = GLOBAL_SCRIPTS.theme.themes()
        if not themes:
            self.error("No themes to display!")
            return
        if self.args:
            return self.switch_display()
        message = list()
        message.append(self.styled_header('Themes'))
        message.append(self.styled_columns(f"{'Theme Name':<70} {'Con/Tot'}"))
        message.append(self.styled_separator())
        for theme in themes:
            members = [part.character for part in theme.participants.all()]
            members_online = [member for member in members if member.sessions.all()]
            message.append(f"{str(theme):<70} {len(members_online):0>3}/{len(members):0>3}")
        message.append(self.styled_footer())
        self.msg('\n'.join(str(l) for l in message))

    def display_column(self):
        return self.styled_columns(f"{'Name':<27}{'Faction':<25}{'Last On':<9}{'Last On':<9}Status")

    def display_participant_row(self, viewer, participant):
        char = participant.character
        char_name = char.key
        faction = char.db._primary_faction.key if char.db._primary_faction else ''
        last_on = char.idle_or_last(viewer)
        list_type = participant.list_type
        status = char.db.theme_status if char.db.theme_status else '???'
        return f"{char_name[:26]:<27}{faction[:24]:<25}{last_on.ljust(9)}{list_type[:8]:<9}{status[:8]}"

    def switch_display(self):
        theme = GLOBAL_SCRIPTS.theme.find_theme(self.session, self.lhs)
        if not theme:
            self.error("No theme name entered.")
            return
        message = list()
        message.append(self.styled_header(f"Theme: {theme}"))
        if theme.description:
            message.append(theme.description)
        message.append(self._blank_separator)
        message.append(self.display_column())
        message.append(self._blank_separator)
        for participant in theme.participants.order_by('db_character__db_key'):
            message.append(self.display_participant_row(self.caller, participant))
        message.append(self._blank_footer)
        self.msg('\n'.join(str(l) for l in message))

    def switch_assign(self):
        theme = GLOBAL_SCRIPTS.theme.find_theme(self.session, self.lhs)
        if not len(self.rhslist) == 2:
            raise ValueError("Usage: @theme/assign <theme>=<character>,<list type>")
        char_name, list_type = self.rhslist
        character = self.search_one_character(char_name)
        GLOBAL_SCRIPTS.theme.theme_add_character(self.session, theme, character, list_type)

    def switch_remove(self):
        theme = GLOBAL_SCRIPTS.theme.find_theme(self.session, self.lhs)
        character = self.search_one_character(self.rhs)
        GLOBAL_SCRIPTS.theme.theme_remove_character(self.session, theme, character)

    def switch_type(self):
        theme = GLOBAL_SCRIPTS.theme.find_theme(self.session, self.lhs)
        if not len(self.rhslist) == 2:
            raise ValueError("Usage: @theme/type <theme>=<character>,<list type>")
        char_name, list_type = self.rhslist
        character = self.search_one_character(char_name)
        GLOBAL_SCRIPTS.theme.participant_change_type(self.session, theme, character, list_type)

    def switch_status(self):
        character = self.search_one_character(self.lhs)
        GLOBAL_SCRIPTS.theme.character_change_status(self.session, character, self.rhs)

    def switch_describe(self):
        GLOBAL_SCRIPTS.theme.set_description(self.session, self.lhs, self.rhs)

    def switch_primary(self):
        character = self.search_one_character(self.lhs)
        GLOBAL_SCRIPTS.theme.character_change_primary(self.session, character, self.rhs)

    def switch_note(self):
        pass
