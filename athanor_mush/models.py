import hashlib
from django.db import models
from django.db.models import Q
from athanor.utils.text import partial_match
from evennia.utils.utils import lazy_property


class MushObject(models.Model):
    obj = models.OneToOneField('objects.ObjectDB', related_name='mush', null=True, on_delete=models.SET_NULL)
    account = models.OneToOneField('accounts.AccountDB', related_name='mush', null=True, on_delete=models.SET_NULL)
    group = models.OneToOneField('factions.FactionBridge', related_name='mush', null=True, on_delete=models.SET_NULL)
    board = models.OneToOneField('athanor_forum.ForumBoardBridge', related_name='mush', null=True, on_delete=models.SET_NULL)
    fclist = models.OneToOneField('themes.ThemeBridge', related_name='mush', null=True, on_delete=models.SET_NULL)
    #area = models.OneToOneField('building.AreaBridge', related_name='mush', null=True, on_delete=models.SET_NULL)
    dbref = models.CharField(max_length=15, db_index=True)
    objid = models.CharField(max_length=30, unique=True, db_index=True)
    type = models.PositiveSmallIntegerField(db_index=True)
    name = models.CharField(max_length=80)
    created = models.DateTimeField()
    location = models.ForeignKey('self', related_name='contents', null=True, on_delete=models.SET_NULL)
    destination = models.ForeignKey('self', related_name='exits_to', null=True, on_delete=models.SET_NULL)
    parent = models.ForeignKey('self', related_name='children', null=True, on_delete=models.SET_NULL)
    owner = models.ForeignKey('self', related_name='owned', null=True, on_delete=models.SET_NULL)
    flags = models.TextField(blank=True)
    powers = models.TextField(blank=True)
    recreated = models.BooleanField(default=False)

    def __unicode__(self):
        return self.name

    def __repr__(self):
        return '<PennObj %s: %s>' % (self.dbref, self.name)

    def aliases(self):
        ali = self.mushget('alias', check_parent=False)
        if ali:
            return ali.split(';')
        return []

    def mushget(self, attrname, default='', check_parent=True):
        if not attrname:
            return False
        attr = self.attrs.filter(attr__key__iexact=attrname).first()
        if attr:
            return attr.value.replace('%r', '%R').replace('%t', '%T')
        if check_parent and self.parent:
            parent_attr = self.parent.mushget(attrname, check_parent=check_parent)
            if parent_attr:
                return parent_attr
            else:
                return default
        else:
            return default

    def hasattr(self, attrname):
        if not attrname:
            return False
        attr = self.attrs.filter(attr__key__iexact=attrname).first()
        return bool(attr)

    def lattr(self, attrpattern):
        if not attrpattern:
            return list()
        attrpattern = attrpattern.replace('`**','`\S+')
        attrpattern = r'^%s$' % attrpattern.replace('*','\w+')
        check = [attr.attr.key for attr in self.attrs.filter(attr__key__iregex=attrpattern)]
        if not check:
            return list()
        return check

    def lattrp(self, attrpattern):
        attrset = list()
        attrset += self.lattr(attrpattern)
        if self.parent:
            attrset += self.parent.lattrp(attrpattern)
        return list(set(attrset))

    def lattrp2(self, attrpattern):
        attrset = list()
        attrset += self.lattr(attrpattern)
        if self.parent:
            attrset += self.parent.lattrp2(attrpattern)
        return attrset

    def getstat(self, attrname, stat):
        attr = self.mushget(attrname)
        if not attr:
            return
        attr_dict = dict()
        for element in attr.split('|'):
            name, value = element.split('~', 1)
            attr_dict[name] = value
        find_stat = partial_match(stat, attr_dict)
        if not find_stat:
            return
        return attr_dict[find_stat]

    @property
    def exits(self):
        return self.contents.filter(type=4)

    def check_password(self, password):
        old_hash = self.mushget('XYXXY')
        if not old_hash:
            return False
        if old_hash.startswith('1:'):
            hash_against = old_hash.split(':')[2]
            check = hashlib.new('sha1')
            check.update(password)
            return check.hexdigest() == hash_against
        elif old_hash.startswith('2:'):
            hash_against = old_hash.split(':')[2]
            salt = hash_against[0:2]
            hash_against = hash_against[2:]
            check = hashlib.new('sha1')
            check.update('%s%s' % (salt, password))
            return check.hexdigest() == hash_against

    @lazy_property
    def entity(self):
        from .. core.gameentity import EntityMap
        found, created = EntityMap.objects.get_or_create(db_model='mushdb', db_instance=self.id,
                                                         db_owner_date_created=self.created, db_key=self.name)
        if created:
            found.save()
        return found


def cobj(abbr=None):
    if not abbr:
        raise ValueError("No abbreviation entered!")
    code_object = MushObject.objects.filter(name='Core Code Parent <CCP>').first()
    if not code_object:
        raise ValueError("Core Code Parent <CCP> not found!")
    search_name = 'COBJ`%s' % abbr.upper()
    found_attr = code_object.attrs.filter(attr__key=search_name).first()
    if not found_attr:
        raise ValueError("COBJ`%s not found!" % abbr.upper())
    dbref = found_attr.value
    if not dbref:
        raise ValueError("Cannot find DBREF of %s" % abbr.upper())
    return objmatch(dbref)


def pmatch(dbref=None):
    if not dbref:
        return False
    find = MushObject.objects.filter(Q(dbref=dbref) | Q(objid=dbref)).exclude(obj=None).first()
    if find:
        return find.obj
    return False


def objmatch(dbref=None):
    if not dbref:
        return False
    find = MushObject.objects.filter(Q(dbref=dbref) | Q(objid=dbref)).first()
    if find:
        return find
    return False


class MushAttributeName(models.Model):
    key = models.CharField(max_length=200, unique=True, db_index=True)


class MushAttribute(models.Model):
    dbref = models.ForeignKey(MushObject, related_name='attrs', on_delete=models.CASCADE)
    attr = models.ForeignKey(MushAttributeName, related_name='characters', on_delete=models.SET_NULL)
    value = models.TextField(blank=True)


    class Meta:
        unique_together = (("dbref", "attr"),)

