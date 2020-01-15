import MySQLdb
import MySQLdb.cursors as cursors
import datetime
import pytz
import random

from django.conf import settings
from evennia import GLOBAL_SCRIPTS
from django.db.models import Q

from . convpenn import PennParser, process_penntext
from . models import MushObject, cobj, pmatch, objmatch, MushAttributeName, MushAttribute
from athanor.utils.text import penn_substitutions
from athanor.core.command import AthanorCommand


def from_mushtimestring(timestring):
    try:
        convert = datetime.datetime.strptime(timestring, '%c').replace(tzinfo=pytz.utc)
    except ValueError:
        return None
    return convert


class CmdPennImport(AthanorCommand):
    key = '@penn'
    system_name = 'IMPORT'
    locks = 'cmd:perm(Developers)'
    admin_switches = ['initialize', 'areas', 'grid', 'accounts', 'groups', 'bbs', 'themes', 'radio', 'jobs', 'scenes']
    
    def report_status(self, message):
        print(message)
        # self.sys_msg(message)
    
    def sql_cursor(self):
        if hasattr(self, 'cursor'):
            return self.cursor
        sql_dict = settings.PENNMUSH_SQL_DICT
        self.sql = MySQLdb.connect(host=sql_dict['site'], user=sql_dict['username'],
                             passwd=sql_dict['password'], db=sql_dict['database'], cursorclass=cursors.DictCursor)
        self.cursor = self.sql.cursor()
        return self.cursor

    def at_post_cmd(self):
        if hasattr(self, 'sql'):
            self.sql.close()

    def switch_initialize(self):
        try:
            mush_import = PennParser('outdb', self.report_status)
        except IOError as err:
            self.error(str(err))
            self.error("Had an IOError. Did you put the outdb in the game's root directory?")
            return
        except ValueError as err:
            self.error(str(err))
            return

        penn_objects = mush_import.mush_data

        obj_dict = dict()

        dbrefs = sorted(penn_objects.keys(), key=lambda dbr: int(dbr.strip('#')))
        db_count = len(dbrefs)
        for count, entity in enumerate(dbrefs, start=1):
            penn_data = penn_objects[entity]
            self.report_status(f"Processing MushObject {count} of {db_count} - {penn_data['objid']}: {penn_data['name']}")
            entry, created = MushObject.objects.get_or_create(dbref=entity, objid=penn_data['objid'],
                                                              type=penn_data['type'], name=penn_data['name'],
                                                              flags=penn_data['flags'], powers=penn_data['powers'],
                                                              created=from_unixtimestring(penn_data['created']))
            if created:
                entry.save()

            obj_dict[entity] = entry

        def set_attr(penn_data, entry, attr, target):
            try:
                if penn_data[attr] in obj_dict:
                    setattr(entry, target, obj_dict[penn_data[attr]])
            except Exception as e:
                self.report_status(f"ERROR DETECTED ON {penn_data}: {entry}, {attr} -> {target}")
                raise e

        for counter, entity in enumerate(dbrefs, start=1):
            penn_data = penn_objects[entity]
            entry = obj_dict[entity]
            self.report_status(f"Performing Secondary Processing on MushObject {counter} of {db_count} - {entry.objid}: {entry.name}")
            for attr, target in (('parent', 'parent'), ('owner', 'owner')):
                set_attr(penn_data, entry, attr, target)

            if penn_data['type'] == 4:  # For exits!
                for attr, target in (('location', 'destination'), ('exits', 'location')):
                    set_attr(penn_data, entry, attr, target)
            else:
                set_attr(penn_data, entry, 'location', 'location')
            entry.save()

            attr_dict = dict()

            for attr, value in penn_data['attributes'].items():
                attr_upper = attr.upper()
                if attr_upper in attr_dict:
                    attr_name = attr_dict[attr_upper]
                else:
                    attr_name, created = MushAttributeName.objects.get_or_create(key=attr_upper)
                    if created:
                        attr_name.save()
                    attr_dict[attr_upper] = attr_name
                attr_entry, created2 = entry.attrs.get_or_create(attr=attr_name, value=penn_substitutions(value))
                if not created2:
                    attr_entry.save()

        self.report_status(f"Imported {db_count} MushObjects and {MushAttribute.objects.count()} MushAttributes into Django. Ready for additional operations.")

    def switch_area_recursive(self, district, parent=None):
        area = district.area
        if not area:
            area = GLOBAL_SCRIPTS.area.create_area(self.session, district.name, parent=parent)
            district.area = area.area_bridge
            district.save()
            self.report_status(f"Created Area: {area}")
        for dist in district.children.filter(type=2).order_by('name'):
            self.switch_area_recursive(dist, area)

    def switch_areas(self):
        district_parent = cobj('district')
        for district in district_parent.children.filter(type=2).order_by('name'):
            self.switch_area_recursive(district, parent=None)
        self.report_status("All done with Areas!")

    def switch_grid(self):
        area_con = GLOBAL_SCRIPTS.area
        mush_rooms = MushObject.objects.filter(type=1, obj=None).exclude(Q(parent=None) | Q(parent__area=None))

        mush_rooms_count = len(mush_rooms)

        for counter, mush_room in enumerate(mush_rooms, start=1):
            self.report_status(f"Processing Room {counter} of {mush_rooms_count} - {mush_room.objid}: {mush_room.name}")
            new_room = area_con.create_room(self.session, mush_room.parent.area.db_object, mush_room.name, self.account)
            mush_room.obj = new_room
            mush_room.obj.db.desc = process_penntext(mush_room.mushget('DESCRIBE'))
            mush_room.save()

        mush_exits = MushObject.objects.filter(type=4, obj=None).exclude(Q(location__parent__area=None) | Q(destination__parent__area=None) | Q(location__obj=None) | Q(destination__obj=None))
        mush_exits_count = len(mush_exits)

        for counter, mush_exit in enumerate(mush_exits, start=1):
            self.report_status(f"Processing Exit {counter} of {mush_exits_count} - {mush_exit.objid}: {mush_exit.name} FROM {mush_exit.location.name} TO {mush_exit.destination.name}")
            aliases = None
            alias_text = mush_exit.mushget('alias')
            if alias_text:
                aliases = alias_text.split(';')

            new_exit = area_con.create_exit(self.session, mush_exit.location.parent.area.db_object, mush_exit.name,
                                                  self.account, mush_exit.location.obj, mush_exit.destination.obj,
                                                  aliases=aliases)
            mush_exit.obj = new_exit
            mush_exit.save()

    def random_password(self):
        password = "ABCDEFGHabcdefgh@+-" + str(random.randrange(5000000, 1000000000))
        password_list = list(password)
        random.shuffle(password_list)
        password = ''.join(password_list)
        return password

    def ghost_account(self, objid, name, email):
        par = cobj(abbr='accounts')
        if (found := par.children.filter(objid=objid).first()):
            return found
        dbref, created = objid.split(':')
        ghost, created = par.children.get_or_create(dbref=dbref, objid=objid, created=from_unixtimestring(created),
                                                    location=par, name=name, owner=par, type=par.type, recreated=True)
        if created:
            ghost.save()
        return ghost

    def ghost_character(self, objid, name):
        character = pmatch(objid)
        if character:
            return character
        dbref, timestamp = objid.split(':',1)
        ghost, created = MushObject.objects.get_or_create(dbref=dbref, objid=objid, name=name, created=from_unixtimestring(timestamp), recreated=True,
                           type=8)
        if created:
            ghost.save()
        return ghost

    def get_lost_and_found(self):
        try:
            lost_and_found = GLOBAL_SCRIPTS.accounts.find_account("LostAndFound")
        except:
            lost_and_found = GLOBAL_SCRIPTS.accounts.create_account(self.session, "LostAndFound", 'dummy@dummy.com',
                                                                            self.random_password())
            lost_and_found.db._lost_and_found = True
        return lost_and_found

    def switch_accounts(self):
        accounts_con = GLOBAL_SCRIPTS.accounts

        c = self.sql_cursor()

        c.execute("""SELECT * FROM volv_accounts ORDER BY account_date_created ASC""")
        mush_accounts = c.fetchall()

        mush_accounts_obj = {obj.objid: obj for obj in cobj(abbr='accounts').children.filter()}
        mush_accounts_count = len(mush_accounts)

        mush_account_dict = dict()

        for counter, mush_acc in enumerate(mush_accounts, start=1):
            objid = mush_acc['account_objid']
            old_name = mush_acc['account_name']
            old_email = mush_acc['account_email']
            if not (obj := mush_accounts_obj.get(objid, None)):
                obj = self.ghost_account(objid, old_name, old_email)
                mush_accounts_obj[objid] = obj
            if obj.account is not None:
                continue
            password = self.random_password()
            username = f"mush_acc_{mush_acc['account_id']}"
            email = f"{username}@ourgame.org"
            self.report_status(f"Processing Account {counter} of {mush_accounts_count} - {mush_acc.objid}: {mush_acc.name} / {old_email}. New username: {username} - Password: {password}")
            new_account = accounts_con.create_account(self.session, username, email, password)
            obj.account = new_account
            obj.save()
            new_account.db._penn_import = True
            new_account.db._penn_name = mush_acc.name
            new_account.db._penn_email = old_email
            mush_account_dict[mush_acc['account_id']] = new_account
        self.report_status(f"Imported {mush_accounts_count} PennMUSH Accounts!")

        lost_and_found = self.get_lost_and_found()
        self.report_status(f"Acquired Lost and Found Account: {lost_and_found}")

        chars_con = GLOBAL_SCRIPTS.characters

        c.execute("""SELECT * FROM volv_character""")
        mush_characters = c.fetchall()

        mush_characters_obj = MushObject.objects.filter(type=8, obj=None).exclude(powers__icontains='Guest')
        mush_characters_count = len(mush_characters)

        for counter, mush_char in enumerate(mush_characters, start=1):
            self.report_status(f"Processing Character {counter} of {mush_characters_count} - {mush_char.objid}: {mush_char.name}")

            objid = mush_char['character_objid']
            old_name = mush_char['character_name']

            if not (obj := mush_characters_obj.get(objid, None)):
                obj = self.ghost_character(objid, old_name)
                mush_characters_obj[objid] = obj

            if obj.obj is not None:
                continue

            acc_id = mush_char['account_id']
            if not (acc := mush_account_dict.get(acc_id, None)):
                if mush_char.parent and mush_char.parent.account:
                    acc = mush_char.parent.account
                    self.report_status(f"Account Found! Will assign to Account: {acc}")
                else:
                    acc = lost_and_found
                    self.report_status("Character has no Account! Will assign to Lost and Found!")
            else:
                self.report_status(f"Account Found! Will assign to Account: {acc}")
            namespace = None if obj.recreated else 0
            new_char = chars_con.create_character(self.session, acc, obj.name, namespace=namespace)
            obj.obj = new_char
            obj.save()
            new_char.db._penn_import = True

            for alias in obj.aliases():
                new_char.aliases.add(alias)
            description = process_penntext(obj.mushget('DESCRIBE'))
            if description:
                self.report_status(f"FOUND DESCRIPTION: {description}")
                new_char.db.desc = description
            last_logout = obj.mushget('LASTLOGOUT')
            if last_logout:
                new_char.db._last_logout = from_mushtimestring(last_logout)

            flags = mush_char.flags.split(' ')

            if acc != lost_and_found:
                set_super = obj.dbref == '#1'
                set_developer = 'WIZARD' in flags
                set_admin = 'ROYALTY' in flags or int(obj.mushget('V`ADMIN', default='0'))
                if set_super:
                    acc.is_superuser = True
                    acc.save()
                    set_developer = False
                    set_admin = False
                    self.report_status(f"Detected #1 GOD. {acc} and {new_char} has been granted Superuser privileges.")
                if set_developer:
                    acc.permissions.add('Developer')
                    set_admin = False
                    self.report_status(f"Detected WIZARD flag. {acc} and {new_char} has been granted Developer privileges.")
                if set_admin:
                    acc.permissions.add('Admin')
                    self.report_status(f"Detected ROYALTY flag or Admin Group Membership. {acc} and {new_char} has been granted Admin privileges.")

        self.report_status(f"Finished importing {mush_characters_count} characters!")

    def switch_info(self):
        pass

    def switch_groups(self):
        faction_con = GLOBAL_SCRIPTS.faction
        faction_typeclass = faction_con.ndb.faction_typeclass

        c = self.sql_cursor()

        c.execute("""SELECT * FROM volv_group ORDER BY group_parent ASC""")
        mush_groups = c.fetchall()
        faction_map = {None: None}

        mush_groups_count = len(mush_groups)

        for counter, mush_group in enumerate(mush_groups, start=1):
            self.report_status(f"Processing MushGroup {counter} of {mush_groups_count} - {mush_group}")

            mush_object = objmatch(mush_group['group_objid'])
            if not mush_object:
                continue

            abbr = mush_group['group_abbr'] if mush_group['group_abbr'] else None
            new_faction = faction_typeclass.create_faction(name=mush_group['group_name'],
                                                           parent=faction_map[mush_group['group_parent']], abbr=abbr,
                                                           tier=mush_group['group_tier'])
            new_faction.save()
            new_faction.db.private = mush_group['group_is_private']
            faction_map[mush_group['group_id']] = new_faction
            mush_object.group = new_faction
            mush_object.save()

        c.execute("""SELECT * FROM volv_group_rank""")
        mush_groups_ranks = c.fetchall()
        role_map = dict()

        mush_groups_ranks_count = len(mush_groups_ranks)

        for counter, mush_group_rank in enumerate(mush_groups_ranks, start=1):
            if mush_group_rank['group_id'] not in faction_map:
                continue
            self.report_status(f"Processing MushGroupRank {counter} of {mush_groups_ranks_count} - {mush_group_rank}")
            faction = faction_map[mush_group_rank['group_id']]
            role_typeclass = faction.get_role_typeclass()
            rank_name = process_penntext(mush_group_rank['group_rank_title'])

            new_role, created = role_typeclass.objects.get_or_create(db_key=rank_name, db_faction=faction)
            if not new_role.sort_order:
                new_role.sort_order = mush_group_rank['group_rank_number']
            if created:
                new_role.save()
            role_map[mush_group_rank['group_rank_id']] = new_role

        c.execute("""SELECT * FROM volv_group_member""")
        mush_groups_members = c.fetchall()

        mush_groups_members_count = len(mush_groups_members)

        for counter, mush_group_member in enumerate(mush_groups_members, start=1):
            if mush_group_member['group_id'] not in faction_map:
                continue
            self.report_status(f"Processing MushGroupMembership {counter} of {mush_groups_members_count} - {mush_group_member}")
            character = pmatch(mush_group_member['character_objid'])
            if not character:
                continue
            faction = faction_map[mush_group_member['group_id']]
            link_typeclass = faction.get_link_typeclass()
            role = role_map[mush_group_member['group_rank_id']]
            super_user = role.sort_order < 3
            group_title = process_penntext(mush_group_member['group_member_title']) if mush_group_member['group_member_title'] else None
            new_link = link_typeclass(db_entity=character.entity, db_faction=faction, db_member=True,
                                      db_is_superuser=super_user, db_key=character.key)
            new_link.save()
            new_link.db.title = group_title
            role_link_typeclass = faction.get_role_link_typeclass()
            new_role_link = role_link_typeclass(db_link=new_link, db_role=role, db_grantable=False, db_key=role.key)
            new_role_link.save()

        from athanor.characters.characters import AthanorPlayerCharacter
        for counter, character in enumerate(AthanorPlayerCharacter.objects.filter_family()):
            if not hasattr(character, 'mush'):
                continue
            tiers = character.mush.mushget('V`TIERS')
            if not tiers:
                continue
            tiers = tiers.split(' ')[0]
            group = objmatch(tiers)
            if not group:
                continue
            character.db._primary_faction = group.group

    def switch_bbs(self):
        forum_con = GLOBAL_SCRIPTS.forum
        category_typeclass = forum_con.ndb.category_typeclass
        board_typeclass = forum_con.ndb.board_typeclass
        thread_typeclass = forum_con.ndb.thread_typeclass
        c = self.sql_cursor()

        c.execute("""SELECT * FROM volv_board ORDER BY group_id ASC,board_number DESC""")
        mush_boards = c.fetchall()
        forum_category_map = dict()
        forum_board_map = dict()

        mush_boards_count = len(mush_boards)

        factions = {obj.objid: obj.group for obj in MushObject.objects.exclude(group=None) if not obj.group.parent}
        factions[None] = None

        new_category = category_typeclass.create_forum_category(key="Public Boards", abbr='')
        forum_category_map[None] = new_category

        for counter, mush_board in enumerate(mush_boards, start=1):
            self.report_status(f"Processing MushBoard {counter} of {mush_boards_count} - {mush_board}")
            faction = factions[mush_board['group_objid']]
            if faction not in forum_category_map:
                new_category = category_typeclass.create_forum_category(key=faction.key, abbr=faction.abbreviation)
                new_category.save()
                forum_category_map[faction] = new_category
            forum_category = forum_category_map[faction]
            new_board = board_typeclass.create_forum_board(category=forum_category, key=mush_board['board_name'], order=mush_board['board_number'])
            if mush_board['board_mandatory']:
                new_board.forum_board_bridge.mandatory = True
            forum_board_map[mush_board['board_id']] = new_board

        forum_thread_map = dict()
        forum_post_map = dict()

        c.execute("""SELECT * FROM volv_bbpost ORDER BY post_display_num ASC""")
        mush_posts = c.fetchall()

        mush_posts_count = len(mush_posts)

        for counter, mush_post in enumerate(mush_posts, start=1):
            self.report_status(f"Processing MushPost {counter} of {mush_posts_count} - {mush_post}")
            obj = self.ghost_character(mush_post['entity_objid'], mush_post['entity_name'])
            board = forum_board_map[mush_post['board_id']]
            created = mush_post['post_date_created']
            modified = mush_post['post_date_modified']
            title = process_penntext(mush_post['post_title'])
            new_thread = thread_typeclass.create_forum_thread(board=board, key=title,
                                                              order=mush_post['post_display_num'], obj=obj,
                                                              date_created=created, date_modified=modified)


            new_thread.save()
            forum_thread_map[mush_post['post_id']] = new_thread
            new_post = post_typeclass(db_entity=entity, db_date_created=created, db_date_modified=modified,
                                      db_thread=new_thread, db_order=1, db_key=title,
                                      db_body=process_penntext(mush_post['post_text']))
            new_post.save()

        c.execute("""SELECT * FROM volv_bbcomment ORDER BY comment_display_num ASC""")
        mush_comments = c.fetchall()

        from django.db.models import Max
        mush_comments_count = len(mush_comments)

        for counter, mush_comment in enumerate(mush_comments, start=1):
            self.report_status(f"Processing MushPostComment {counter} of {mush_comments_count} - {mush_comment}")
            entity = self.ghost_character(mush_comment['entity_objid'], mush_comment['entity_name']).entity
            thread = forum_thread_map[mush_comment['post_id']]
            created = mush_comment['comment_date_created']
            modified = mush_comment['comment_date_modified']
            stats = thread.posts.aggregate(Max('db_order'))
            order = stats['db_order__max'] + 1
            new_post = post_typeclass(db_entity=entity, db_date_created=created, db_date_modified=modified,
                                      db_order=order, db_key='Imported MUSH Comment',
                                      db_body=process_penntext(mush_comment['comment_text']), db_thread=thread)
            new_post.save()

        self.report_status("ALl done importing BBS!")

    def switch_themes(self):
        theme_con = GLOBAL_SCRIPTS.theme
        c = self.sql_cursor()
        c.execute("""SELECT * FROM volv_theme """)
        mush_themes = c.fetchall()
        c.execute("""SELECT * FROM volv_theme_member""")
        mush_theme_members = c.fetchall()

        theme_map = dict()

        mush_theme_count = len(mush_themes)

        for counter, mush_theme in enumerate(mush_themes, start=1):
            self.report_status(f"Processing MushTheme {counter} of {mush_theme_count} - {mush_theme['theme_name']}")
            theme = theme_con.create_theme(self.session, mush_theme['theme_name'], process_penntext(mush_theme['theme_description']))
            theme_map[mush_theme['theme_id']] = theme

        mush_theme_members_count = len(mush_theme_members)

        for counter, mush_theme_member in enumerate(mush_theme_members, start=1):
            self.report_status(f"Processing MushThemeMembership {counter} of {mush_theme_members_count} - {mush_theme_member}")
            character = pmatch(mush_theme_member['character_objid'])
            if not character:
                continue
            theme = theme_map[mush_theme_member['theme_id']]
            list_type = mush_theme_member['tmember_type']
            theme.add_character(character, list_type)
            character.db.theme_status = mush_theme_member['character_status']

        self.report_status("All done importing Themes!")

    def switch_radio(self):
        pass

    def switch_jobs(self):
        pass

    def switch_scenes(self):
        rplog_con = GLOBAL_SCRIPTS.events
        plot_typeclass = rplog_con.ndb.plot_typeclass
        runner_typeclass = rplog_con.ndb.runner_typeclass
        event_typeclass = rplog_con.ndb.event_typeclass
        participant_typeclass = rplog_con.ndb.participant_typeclass
        source_typeclass = rplog_con.ndb.source_typeclass
        codename_typeclass = rplog_con.ndb.codename_typeclass
        action_typeclass = rplog_con.ndb.action_typeclass
        c = self.sql_cursor()

        c.execute("""SELECT * FROM volv_plot""")
        mush_plots = c.fetchall()
        plots_map = dict()
        mush_plots_count = len(mush_plots)

        for counter, mush_plot in enumerate(mush_plots, start=1):
            self.report_status(f"Processing MushPlot {counter} of {mush_plots_count} - {mush_plot}")
            new_plot = plot_typeclass(db_key=mush_plot['plot_title'], db_pitch=process_penntext(mush_plot['plot_pitch']),
                                      db_summary=process_penntext(mush_plot['plot_summary']),
                                      db_outcome=process_penntext(mush_plot['plot_outcome']),
                                      db_date_start=mush_plot['plot_date_start'], db_date_end=mush_plot['plot_date_end'])
            new_plot.save()
            plots_map[mush_plot['plot_id']] = new_plot

        c.execute("""SELECT * FROM volv_runner""")
        mush_runners = c.fetchall()
        mush_runners_count = len(mush_runners)

        for counter, mush_runner in enumerate(mush_runners, start=1):
            self.report_status(f"Processing MushPlotRunners {counter} of {mush_runners_count} - {mush_runner}")
            entity = self.ghost_character(mush_runner['character_objid'], mush_runner['character_name']).entity
            plot = plots_map[mush_runner['plot_id']]
            new_runner = runner_typeclass(db_plot=plot, db_entity=entity, db_runner_type=mush_runner['runner_type'])
            new_runner.save()

        c.execute("""SELECT * FROM volv_scene""")
        mush_scenes = c.fetchall()
        events_map = dict()
        mush_scenes_count = len(mush_scenes)

        for counter, mush_scene in enumerate(mush_scenes, start=1):
            self.report_status(f"Processing MushScene {counter} of {mush_scenes_count} - {mush_scene}")
            pitch = process_penntext(mush_scene['scene_pitch'])
            outcome = process_penntext(mush_scene['scene_outcome'])
            new_event = event_typeclass(db_key=mush_scene['scene_title'], db_pitch=pitch, db_outcome=outcome,
                                        db_date_scheduled=mush_scene['scene_date_scheduled'],
                                        db_date_created=mush_scene['scene_date_created'],
                                        db_date_started=mush_scene['scene_date_started'],
                                        db_date_finished=mush_scene['scene_date_finished'],
                                        db_status=mush_scene['scene_status'])
            new_event.save()
            events_map[mush_scene['scene_id']] = new_event

        c.execute("""SELECT * FROM vol_plotlink""")
        plot_links = c.fetchall()
        plot_links_count = len(plot_links)

        for counter, plot_link in enumerate(plot_links, start=1):
            self.report_status(f"Processing MushPlotLink {counter} of {plot_links_count} - {plot_link}")
            plot = plots_map[plot_link['plot_id']]
            event = events_map[plot_link['scene_id']]
            event.plots.add(plot)

        c.execute("""SELECT * FROM vol_action_source""")
        action_sources = c.fetchall()
        action_sources_count = len(action_sources)
        event_source_map = dict()

        for counter, action_source in enumerate(action_sources, start=1):
            self.report_status(f"Processing MushActionSource {counter} of {action_sources_count} - {action_source}")
            event = events_map[action_source['scene_id']]
            new_source, created = source_typeclass.objects.get_or_create(db_key=action_source['source_name'], db_event=event,
                                          db_source_type=action_source['source_type'])
            if created:
                new_source.save()
            event_source_map[action_source['source_id']] = new_source

        c.execute("""SELECT * FROM volv_actor""")
        mush_actors = c.fetchall()
        participant_map = dict()
        mush_actors_count = len(mush_actors)

        for counter, mush_actor in enumerate(mush_actors, start=1):
            self.report_status(f"Processing MushActor {counter} of {mush_actors_count} - {mush_actor}")
            event = events_map[mush_actor['scene_id']]
            entity = self.ghost_character(mush_actor['character_objid'], mush_actor['character_name']).entity
            new_participant = participant_typeclass(db_key=entity.key, db_event=event, db_entity=entity,
                                                    db_participant_type=mush_actor['actor_type'],
                                                    db_action_count=mush_actor['action_count'])
            new_participant.save()
            participant_map[mush_actor['actor_id']] = new_participant


        c.execute("""SELECT * FROM volv_action ORDER BY scene_id ASC,action_date_created ASC""")
        mush_actions = c.fetchall()
        action_map = dict()
        mush_actions_count = len(mush_actions)
        cur_scene = None
        order_counter = 0
        for counter, mush_action in enumerate(mush_actions, start=1):
            self.report_status(f"Processing MushAction {counter} of {mush_actions_count} - {mush_action}")
            scene_id = mush_action['scene_id']
            event = events_map[scene_id]
            if scene_id != cur_scene:
                order_counter = 0
                cur_scene = scene_id
            participant = participant_map[mush_action['actor_id']]
            source = event_source_map[mush_action['source_id']]
            new_action = action_typeclass(db_event=event, db_participant=participant, db_source=source,
                                          db_ignore=mush_action['action_is_deleted'], db_sort_order=order_counter,
                                          db_text=process_penntext(mush_action['action_text']))
            new_action.save()

        self.report_status("All done importing Rp Logs!")
