from datetime import datetime, timedelta
from dateutil.parser import parse
import requests

from astropy.time import Time, TimezoneInfo
from crispy_forms.layout import Layout, Div, Fieldset
from django import forms
from django.core.cache import cache

from tom_alerts.alerts import GenericAlert, GenericBroker, GenericDashBroker, GenericQueryForm
from tom_common.templatetags.tom_common_extras import truncate_number
from tom_targets.models import Target
from tom_targets.templatetags.targets_extras import deg_to_sexigesimal

ALERCE_URL = 'https://alerce.online'
ALERCE_SEARCH_URL = 'https://ztf.alerce.online/query'
ALERCE_CLASSES_URL = 'https://ztf.alerce.online/get_current_classes'

SORT_CHOICES = [('nobs', 'Number Of Epochs'),
                ('lastmjd', 'Last Detection'),
                ('pclassrf', 'Late Probability'),
                ('pclassearly', 'Early Probability')]

PAGES_CHOICES = [
    (i, i) for i in [1, 5, 10, 15]
]

RECORDS_CHOICES = [
    (i, i) for i in [20, 100, 500]
]


class ALeRCEQueryForm(GenericQueryForm):

    nobs__gt = forms.IntegerField(
        required=False,
        label='Detections Lower',
        widget=forms.TextInput(attrs={'placeholder': 'Min number of epochs'})
    )
    nobs__lt = forms.IntegerField(
        required=False,
        label='Detections Upper',
        widget=forms.TextInput(attrs={'placeholder': 'Max number of epochs'})
    )
    classrf = forms.TypedChoiceField(
        required=False,
        label='Late Classifier (Random Forest)',
        choices=[],  # Choices are populated dynamically in the constructor
        coerce=int
    )
    pclassrf = forms.FloatField(
        required=False,
        label='Classifier Probability (Random Forest)'
    )
    classearly = forms.TypedChoiceField(
        required=False,
        label='Early Classifier (Stamp Classifier)',
        choices=[],  # Choices are populated dynamically in the constructor
        coerce=int
    )
    pclassearly = forms.FloatField(
        required=False,
        label='Classifier Probability (Stamp Classifier)'
    )
    ra = forms.IntegerField(
        required=False,
        label='RA',
        widget=forms.TextInput(attrs={'placeholder': 'RA (Degrees)'})
    )
    dec = forms.IntegerField(
        required=False,
        label='Dec',
        widget=forms.TextInput(attrs={'placeholder': 'Dec (Degrees)'})
    )
    sr = forms.IntegerField(
        required=False,
        label='Search Radius',
        widget=forms.TextInput(attrs={'placeholder': 'SR (Degrees)'})
    )
    mjd__gt = forms.FloatField(
        required=False,
        label='Min date of first detection ',
        widget=forms.TextInput(attrs={'placeholder': 'Date (MJD)'}),
        min_value=0.0
    )
    mjd__lt = forms.FloatField(
        required=False,
        label='Max date of first detection',
        widget=forms.TextInput(attrs={'placeholder': 'Date (MJD)'}),
        min_value=0.0
    )
    relative_mjd__gt = forms.FloatField(
        required=False,
        label='Relative date of object discovery.',
        widget=forms.TextInput(attrs={'placeholder': 'Hours'}),
        min_value=0.0
    )
    sort_by = forms.ChoiceField(
            choices=SORT_CHOICES,
            required=False,
            label='Sort By'
    )
    max_pages = forms.TypedChoiceField(
            choices=PAGES_CHOICES,
            required=False,
            label='Max Number of Pages',
            coerce=int
    )
    records = forms.TypedChoiceField(
            choices=RECORDS_CHOICES,
            required=False,
            label='Records per page',
            coerce=int
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.fields['classearly'].choices = self.early_classifier_choices()
        self.fields['classrf'].choices = self.late_classifier_choices()

        self.helper.layout = Layout(
            self.common_layout,
            Fieldset(
                'Number of Epochs',
                Div(
                    Div(
                        'nobs__gt',
                        css_class='col',
                    ),
                    Div(
                        'nobs__lt',
                        css_class='col',
                    ),
                    css_class='form-row',
                )
            ),
            Fieldset(
                'Classification Filters',
                Div(
                    Div(
                        'classrf',
                        'classearly',
                        css_class='col'
                    ),
                    Div(
                        'pclassrf',
                        'pclassearly',
                        css_class='col',
                    ),
                    css_class='form-row',
                )
            ),
            Fieldset(
                'Location Filters',
                Div(
                    Div(
                        'ra',
                        css_class='col'
                    ),
                    Div(
                        'dec',
                        css_class='col'
                    ),
                    Div(
                        'sr',
                        css_class='col'
                    ),
                    css_class='form-row'
                )
            ),
            Fieldset(
                'Time Filters',
                Div(
                    Fieldset(
                        'Relative time',
                        Div(
                            'relative_mjd__gt',
                            css_class='col',
                        ),
                        css_class='col'
                    ),
                    Fieldset(
                        'Absolute time',
                        Div(
                            Div(
                                'mjd__gt',
                                css_class='col',
                            ),
                            Div(
                                'mjd__lt',
                                css_class='col',
                            ),
                            css_class='form-row'
                        )
                    ),
                    css_class='form-row'
                )
            ),
            Fieldset(
                'General Parameters',
                Div(
                    Div(
                        'sort_by',
                        css_class='col'
                    ),
                    Div(
                        'records',
                        css_class='col'
                    ),
                    Div(
                        'max_pages',
                        css_class='col'
                    ),
                    css_class='form-row'
                )
            ),
        )

    @staticmethod
    def _get_classifiers():
        cached_classifiers = cache.get('alerce_classifiers')

        if not cached_classifiers:
            response = requests.get(ALERCE_CLASSES_URL)
            response.raise_for_status()
            cached_classifiers = response.json()

        return cached_classifiers

    def clean_sort_by(self):
        return self.cleaned_data['sort_by'] if self.cleaned_data['sort_by'] else 'nobs'

    def clean_records(self):
        return self.cleaned_data['records'] if self.cleaned_data['records'] else 20

    def clean_relative_mjd__gt(self):
        if self.cleaned_data['relative_mjd__gt']:
            return Time(datetime.now() - timedelta(hours=self.cleaned_data['relative_mjd__gt'])).mjd
        return None

    def clean(self):
        cleaned_data = super().clean()

        # Ensure that all cone search fields are present
        if any(cleaned_data[k] for k in ['ra', 'dec', 'sr']) and not all(cleaned_data[k] for k in ['ra', 'dec', 'sr']):
            raise forms.ValidationError('All of RA, Dec, and Search Radius must be included to execute a cone search.')

        # Ensure that both relative and absolute time filters are not present
        if any(cleaned_data[k] for k in ['mjd__lt', 'mjd__gt']) and cleaned_data.get('relative_mjd__gt'):
            raise forms.ValidationError('Cannot filter by both relative and absolute time.')

        # Ensure that absolute time filters have sensible values
        if all(cleaned_data[k] for k in ['mjd__lt', 'mjd__gt']) and cleaned_data['mjd__lt'] <= cleaned_data['mjd__gt']:
            raise forms.ValidationError('Min date of first detection must be earlier than max date of first detection.')

        return cleaned_data

    def early_classifier_choices(self):
        return [(None, '')] + sorted([(c['id'], c['name']) for c in self._get_classifiers()['early']],
                                     key=lambda classifier: classifier[1])

    def late_classifier_choices(self):
        return [(None, '')] + sorted([(c['id'], c['name']) for c in self._get_classifiers()['late']],
                                     key=lambda classifier: classifier[1])


class ALeRCEBroker(GenericBroker, GenericDashBroker):
    name = 'ALeRCE'
    form = ALeRCEQueryForm

    def _clean_coordinate_parameters(self, parameters):
        if all([parameters['ra'], parameters['dec'], parameters['sr']]):
            return {
                'ra': parameters['ra'],
                'dec': parameters['dec'],
                'sr': parameters['sr']
            }
        else:
            return None

    def _clean_date_parameters(self, parameters):
        dates = {}

        if any(parameters[k] for k in ['mjd__gt', 'mjd__lt']):
            dates = {'firstmjd': {}}
            if parameters['mjd__gt']:
                dates['firstmjd']['min'] = parameters['mjd__gt']
            if parameters['mjd__lt']:
                dates['firstmjd']['max'] = parameters['mjd__lt']
        elif parameters['relative_mjd__gt']:
            dates = {'firstmjd': {'min': parameters['relative_mjd__gt']}}

        return dates

    def _clean_filter_parameters(self, parameters):
        filters = {}

        if any(parameters[k] is not None for k in ['nobs__gt', 'nobs__lt']):
            filters['nobs'] = {}
            if parameters['nobs__gt']:
                filters['nobs']['min'] = parameters['nobs__gt']
            if parameters['nobs__lt']:
                filters['nobs']['max'] = parameters['nobs__lt']
        filters.update({k: parameters[k]
                        for k in ['classrf', 'pclassrf', 'classearly', 'pclassearly']
                        if parameters[k]})

        return filters

    def _clean_parameters(self, parameters):
        payload = {
            'page': parameters.get('page', 1),
            'records_per_pages': parameters.get('records', 20),
            'sortBy': parameters.get('sort_by', 'nobs'),
            'query_parameters': {}
        }

        if parameters.get('total'):
            payload['total'] = parameters.get('total')

        payload['query_parameters']['filters'] = self._clean_filter_parameters(parameters)

        coordinates = self._clean_coordinate_parameters(parameters)
        if coordinates:
            payload['query_parameters']['coordinates'] = coordinates

        payload['query_parameters']['dates'] = self._clean_date_parameters(parameters)

        return payload

    def fetch_alerts(self, parameters):
        payload = self._clean_parameters(parameters)
        print(payload)
        response = requests.post(ALERCE_SEARCH_URL, json=payload)
        response.raise_for_status()
        parsed = response.json()
        alerts = [alert_data for alert, alert_data in parsed['result'].items()]
        if parsed['page'] < parsed['num_pages'] and parsed['page'] != parameters['max_pages']:
            parameters['page'] = parameters.get('page', 1) + 1
            parameters['total'] = parsed.get('total')
            alerts += self.fetch_alerts(parameters)
        return iter(alerts)

    def fetch_alert(self, id):
        """
        The response for a single alert is as follows:

        {
            "total": 1,
            "num_pages": 1,
            "page": 1,
            "result": {
                "ZTF20acnsdjd": {
                  "oid": "ZTF20acnsdjd",
                  other alert values
                }
            }
        }
        """
        payload = {
            'query_parameters': {
                'filters': {
                    'oid': id
                }
            }
        }
        response = requests.post(ALERCE_SEARCH_URL, json=payload)
        response.raise_for_status()
        return list(response.json()['result'].items())[0][1]

    def to_target(self, alert):
        return Target.objects.create(
            name=alert['oid'],
            type='SIDEREAL',
            ra=alert['meanra'],
            dec=alert['meandec']
        )

    def to_generic_alert(self, alert):
        if alert['lastmjd']:
            timestamp = Time(alert['lastmjd'], format='mjd', scale='utc').to_datetime(timezone=TimezoneInfo())
        else:
            timestamp = ''
        url = f'{ALERCE_URL}/object/{alert["oid"]}'

        # Use the smaller value between r and g if both are present, else use the value that is present
        mag = None
        if alert['mean_magpsf_r'] is not None and alert['mean_magpsf_g'] is not None:
            mag = alert['mean_magpsf_g'] if alert['mean_magpsf_r'] > alert['mean_magpsf_g'] else alert['mean_magpsf_r']
        elif alert['mean_magpsf_r'] is not None:
            mag = alert['mean_magpsf_r']
        elif alert['mean_magpsf_g'] is not None:
            mag = alert['mean_magpsf_g']

        if alert['pclassrf'] is not None:
            score = alert['pclassrf']
        elif alert['pclassearly'] is not None:
            score = alert['pclassearly']
        else:
            score = None

        return GenericAlert(
            timestamp=timestamp,
            url=url,
            id=alert['oid'],
            name=alert['oid'],
            ra=alert['meanra'],
            dec=alert['meandec'],
            mag=mag,
            score=score
        )

    def flatten_dash_alerts(self, alerts):
        flattened_alerts = []
        count = 0
        for alert in alerts:
            count += 1
            url = f'{ALERCE_URL}/object/{alert["oid"]}'
            if alert['pclassrf']:
                classifier_suffix = 'classrf'
                classifier_type = 'late'
            else:
                classifier_suffix = 'classearly'
                classifier_type = 'early'
            classifier_name = ''
            for classifier_dict in ALeRCEQueryForm._get_classifiers()[classifier_type]:
                if classifier_dict['id'] == alert[classifier_suffix]:
                    classifier_name = classifier_dict['name']
            flattened_alerts.append({
                'oid': f'[{alert["oid"]}]({url})',
                'meanra': deg_to_sexigesimal(alert['meanra'], 'hms') if alert['meanra'] else None,
                'meandec': deg_to_sexigesimal(alert['meandec'], 'dms') if alert['meandec'] else None,
                'discovery_date': Time(alert['firstmjd'], format='mjd', scale='utc').to_datetime(),
                'classifier': classifier_name,
                'classifier_type': 'Stamp' if classifier_suffix == 'classearly' else 'Light Curve',
                'classifier_probability': truncate_number(alert[f'p{classifier_suffix}']),
                'alert': alert
            })
        print(count)
        return flattened_alerts

    def filter_alerts(self, filters):
        parameters = {'query_name': 'Dash Query', 'broker': self.name, 'nobs__gt': None, 'nobs__lt': 1,
                      'classrf': '', 'pclassrf': None, 'classearly': '', 'pclassearly': None, 'ra': None,
                      'dec': None, 'sr': None, 'mjd__gt': None, 'mjd__lt': None, 'relative_mjd__gt': None,
                      'sort_by': 'lastmjd', 'max_pages': 1, 'records': 20}

        parameters['page'] = filters.get('page_num', 0) + 1  # Dash pages are 0-indexed, ALeRCE is 1-indexed

        if all(k not in filters
               for k in ['oid', 'ra', 'dec', 'discovery_date', 'classifier', 'classifier_probability']):
            parameters['relative_mjd__gt'] = Time(datetime.today() - timedelta(days=7), scale='utc').mjd
            return self.fetch_alerts(parameters)

        parameters['oid'] = filters['oid']['value'] if 'oid' in filters else ''
        if all(k in filters for k in ['ra', 'dec']):
            parameters['ra'] = filters['ra']['value']
            parameters['dec'] = filters['dec']['value']
            parameters['sr'] = 1
        if 'discovery_date' in filters:
            date_range = filters['discovery_date']['value'].strip('\"').split(' - ')
            print(date_range)
            parameters['mjd__gt'] = Time(parse(date_range[0]), format='datetime', scale='utc').mjd
            if len(date_range) >= 2:
                parameters['mjd__lt'] = Time(parse(date_range[1]), format='datetime', scale='utc').mjd
        if 'classifier' in filters:
            classifier_id = None
            classifier_type = ''
            for key, classifier_list in ALeRCEQueryForm._get_classifiers().items():
                for classifier_dict in classifier_list:
                    if filters['classifier']['value'] == classifier_dict['name']:
                        classifier_id = classifier_dict['id']
                        classifier_type = key
                        break
            parameters['classrf'] = classifier_id if classifier_type == 'late' else ''
            parameters['classearly'] = classifier_id if classifier_type == 'early' else ''
        if 'classifier_probability' in filters:
            parameters['classrf'] = filters['classifier_probability']['value']
            parameters['classearly'] = filters['classifier_probability']['value']  # TODO: this will return nothing

        return self.fetch_alerts(parameters)

    def get_dash_columns(self):
        return [
            {'id': 'oid', 'name': 'Object ID', 'type': 'text', 'presentation': 'markdown'},
            {'id': 'meanra', 'name': 'Right Ascension', 'type': 'text'},
            {'id': 'meandec', 'name': 'Declination', 'type': 'text'},
            {'id': 'discovery_date', 'name': 'Discovery Date', 'type': 'datetime'},
            {'id': 'classifier', 'name': 'Class', 'type': 'text'},
            {'id': 'classifier_type', 'name': 'Classifier Type', 'type': 'text'},
            {'id': 'classifier_probability', 'name': 'Classifier Probability', 'type': 'text'},
        ]

    def get_dash_data(self, filters):
        alerts = self.filter_alerts(filters)
        return self.flatten_dash_alerts(alerts)
