INSTALLED_APPS = ['athanor_mush']

GLOBAL_SCRIPTS = dict()

GLOBAL_SCRIPTS['theme'] = {
    'typeclass': 'athanor_mush.controllers.theme.AthanorThemeController',
    'repeats': -1, 'interval': 60, 'desc': 'Theme Controller for Theme System'
}