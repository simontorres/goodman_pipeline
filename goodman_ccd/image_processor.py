from __future__ import print_function
from astropy.io import fits
from astropy import units as u
import ccdproc
from ccdproc import CCDData
import logging
import random
import re
import os
import datetime
from wavmode_translator import SpectroscopicMode

log = logging.getLogger('goodmanccd.imageprocessor')


class ImageProcessor(object):

    def __init__(self, args, data_container):
        self.args = args
        self.instrument = data_container.instrument
        self.technique = data_container.technique
        self.bias = data_container.bias
        self.day_flats = data_container.day_flats
        self.dome_flats = data_container.dome_flats
        self.sky_flats = data_container.sky_flats
        self.data_groups = data_container.data_groups
        self.sun_set = data_container.sun_set_time
        self.sun_rise = data_container.sun_rise_time
        self.morning_twilight = data_container.morning_twilight
        self.afternoon_twilight = data_container.afternoon_twilight
        self.trim_section = self.define_trim_section()
        self.overscan_region = self.get_overscan_region()
        self.spec_mode = SpectroscopicMode()
        self.master_bias = None

    def __call__(self, *args, **kwargs):
        for group in [self.bias, self.day_flats, self.dome_flats, self.sky_flats, self.data_groups]:
            if group is not None:
                for sub_group in group:
                    group_obstype = sub_group.obstype.unique()
                    if len(group_obstype) == 1 and group_obstype[0] == 'BIAS':
                        log.debug('Create Master Bias')
                        self.create_master_bias(sub_group.file.tolist())
                    elif len(group_obstype) == 1 and group_obstype[0] == 'FLAT':
                        log.debug('Create Master FLATS')
                        self.create_master_flats(sub_group)
                    else:
                        log.debug('Process Data Group')
                        if self.technique == 'Spectroscopy':
                            self.process_spectroscopy_science(sub_group)
                        else:
                            log.info('Processing Imaging Science Data')
                            self.process_imaging_science(sub_group)



        print('data groups ', len(self.data_groups))

    def define_trim_section(self):
        # TODO (simon): Consider binning and possibly ROIs for trim section
        log.warning('Determining trim section. Assuming you have only one kind of data in this folder')
        for group in [self.bias, self.day_flats, self.dome_flats, self.sky_flats, self.data_groups]:
            if group is not None:
                # print(self.bias[0])
                image_list = group[0]['file'].tolist()
                sample_image = re.sub('//', '/', self.args.raw_path + '/' + random.choice(image_list))
                header = fits.getheader(sample_image)
                trim_section = header['TRIMSEC']
                log.info('Trim Section: %s', trim_section)
                return trim_section

    def get_overscan_region(self):
        log.warning('Determining Overscan Region. Assuming you have only one kind of data in this folder')
        for group in [self.bias, self.day_flats, self.dome_flats, self.sky_flats, self.data_groups]:
            if group is not None:
                # print(self.bias[0])
                image_list = group[0]['file'].tolist()
                sample_image = re.sub('//', '/', self.args.raw_path + '/' + random.choice(image_list))
                log.debug('Overscan Sample File ' + sample_image)
                header = fits.getheader(sample_image)
                if header['CCDSUM'] == '1 1':
                    log.info('Using predefined overscan region for binning 1x1')
                    if self.technique == 'Spectroscopy':
                        overscan_region = '[5:45,1:4096]'
                    elif self.technique == 'Imaging':
                        log.warning("Imaging mode doesn't have overscan region. Use bias instead.")
                        if self.bias is None:
                            log.error('Bias are needed for Imaging mode')
                        overscan_region = None
                    else:
                        overscan_region = None
                else:
                    log.warning('There is no predefined overscan region')
                    overscan_region = None

                log.info('Overscan Region: %s', overscan_region)
                return overscan_region

    def image_overscan(self, ccd):
        ccd = ccdproc.subtract_overscan(ccd, median=True, fits_section=self.overscan_region)
        ccd.header['HISTORY'] = 'Applied overscan correction ' + self.overscan_region
        return ccd

    def image_trim(self, ccd):
        ccd = ccdproc.trim_image(ccd, fits_section=self.trim_section)
        ccd.header['HISTORY'] = 'Trimmed image to ' + self.trim_section
        return ccd

    def create_master_bias(self, file_list):
        if self.technique == 'Spectroscopy':
            master_bias_list = []
            for image_file in file_list:
                # print(image_file)
                log.debug(self.overscan_region)
                ccd = CCDData.read(self.args.raw_path + '/' + image_file, unit=u.adu)
                o_ccd = self.image_overscan(ccd)
                to_ccd = self.image_trim(o_ccd)
                master_bias_list.append(to_ccd)
            self.master_bias = ccdproc.combine(master_bias_list, method='median', sigma_clip=True,
                                               sigma_clip_low_thresh=3.0, sigma_clip_high_thresh=3.0)
            self.master_bias.write(self.args.red_path + '/' + 'master_bias.fits', clobber=True)
            log.info('Created master bias: ' + self.args.red_path + '/' + 'master_bias.fits')
        elif self.technique == 'Imaging':
            master_bias_list = []
            for image_file in file_list:
                ccd = CCDData.read(self.args.raw_path + '/' + image_file, unit=u.adu)
                t_ccd = self.image_trim(ccd)
                master_bias_list.append(t_ccd)
            self.master_bias = ccdproc.combine(master_bias_list, method='median', sigma_clip=True,
                                               sigma_clip_low_thresh=3.0, sigma_clip_high_thresh=3.0)
            self.master_bias.write(self.args.red_path + '/' + 'master_bias.fits', clobber=True)
            log.info('Created master bias: ' + self.args.red_path + '/' + 'master_bias.fits')

    def create_master_flats(self, flat_group, target_name=''):

        flat_file_list = flat_group.file.tolist()

        master_flat_list = []
        master_flat_name = None

        for f_file in flat_file_list:
            # print(f_file)
            ccd = CCDData.read(self.args.raw_path + '/' + f_file, unit=u.adu)
            if master_flat_name is None:
                master_flat_name = self.name_master_flats(header=ccd.header, group=flat_group, target_name=target_name)
            if self.technique == 'Spectroscopy':
                ccd = self.image_overscan(ccd)
                ccd = self.image_trim(ccd)
            elif self.technique == 'Imaging':
                ccd = self.image_trim(ccd)
                ccd = ccdproc.subtract_bias(ccd, self.master_bias)
            else:
                log.error('Unknown observation technique: ' + self.technique)
            master_flat_list.append(ccd)
        master_flat = ccdproc.combine(master_flat_list,
                                      method='median',
                                      sigma_clip=True,
                                      sigma_clip_low_thresh=1.0,
                                      sigma_clip_high_thresh=1.0)
        master_flat.write(master_flat_name, clobber=True)
        log.info('Created Master Flat: ' + master_flat_name)
        return master_flat
        # print(master_flat_name)

    def name_master_flats(self, header, group, target_name=''):
        master_flat_name = self.args.red_path + '/' + 'master_flat'
        sunset = datetime.datetime.strptime(self.sun_set, "%Y-%m-%dT%H:%M:%S.%f")
        sunrise = datetime.datetime.strptime(self.sun_rise, "%Y-%m-%dT%H:%M:%S.%f")
        afternoon_twilight = datetime.datetime.strptime(self.afternoon_twilight, "%Y-%m-%dT%H:%M:%S.%f")
        morning_twilight = datetime.datetime.strptime(self.morning_twilight, "%Y-%m-%dT%H:%M:%S.%f")
        date_obs = datetime.datetime.strptime(header['DATE-OBS'], "%Y-%m-%dT%H:%M:%S.%f")
        print(sunset, date_obs, afternoon_twilight)
        # print(' ')
        if target_name != '':
            target_name = '_' + target_name
        if (date_obs < sunset) or (date_obs > sunrise):
            dome_sky = '_dome'
        elif (sunset < date_obs < afternoon_twilight) or (morning_twilight < date_obs < sunrise):
            dome_sky = '_sky'
        elif afternoon_twilight < date_obs < morning_twilight:
            dome_sky = '_night'
        else:
            dome_sky = '_other'
        if self.technique == 'Spectroscopy':
            if group.grating.unique()[0] != '<NO GRATING>':
                flat_grating = '_' + re.sub('[A-Za-z_-]', '', group.grating.unique()[0])
                wavmode = self.spec_mode(header=header)
            else:
                flat_grating = '_no_grating'
                wavmode = ''
            flat_slit = re.sub('[A-Za-z" ]', '', group.slit.unique()[0])
            filter2 = group['filter2'].unique()[0]
            if filter2 == '<NO FILTER>':
                filter2 = ''
            else:
                filter2 = '_' + filter2
            master_flat_name += target_name + flat_grating + wavmode + filter2 + '_' + flat_slit + dome_sky + '.fits'
        elif self.technique == 'Imaging':
            flat_filter = re.sub('-', '_', group['filter'].unique()[0])
            master_flat_name += '_' + flat_filter + dome_sky + '.fits'
        # print(master_flat_name)
        return master_flat_name

    def process_spectroscopy_science(self, science_group):
        target_name = ''
        if 'FLAT' in science_group.obstype.unique():
            if 'OBJECT' in science_group.obstype.unique():
                target_name = science_group.object[science_group.obstype == 'OBJECT'].unique()[0]
                print(target_name)
            else:
                log.warning('There are no OBJECT datatype in this group')
                print(science_group)
            flat_sub_group = science_group[science_group.obstype == 'FLAT']
            master_flat = self.create_master_flats(flat_group=flat_sub_group, target_name=target_name)

        elif 'OBJECT' in science_group.obstype.unique() or 'COMP' in science_group.obstype.unique():
            object_comp_group = science_group[((science_group.obstype == 'OBJECT') | (science_group.obstype == 'COMP'))]
            if 'OBJECT' in science_group.obstype.unique():
                target_name = science_group.object[science_group.obstype == 'OBJECT'].unique()[0]

            print(science_group)

    def process_imaging_science(self, imaging_group):
        sample_file = CCDData.read(self.args.raw_path + '/' + random.choice(imaging_group.file.tolist()), unit=u.adu)
        master_flat_name = self.name_master_flats(sample_file.header, imaging_group)
        master_flat = CCDData.read(master_flat_name, unit=u.adu)
        for image_file in imaging_group.file.tolist():
            ccd = CCDData.read(self.args.raw_path + '/' + image_file, unit=u.adu)
            ccd = self.image_trim(ccd)
            if self.args.do_bias:
                pass
            ccd = ccdproc.subtract_bias(ccd, self.master_bias)
            ccd.header['HISTORY'] = 'Bias subtracted image'
            ccd = ccdproc.flat_correct(ccd, master_flat)
            ccd.header['HISTORY'] = 'Flat corrected ' + master_flat_name
            ccd.write(self.args.red_path + '/' + 'fzt_' + image_file, clobber=True)
            log.info('Created science file: ' + self.args.red_path + '/' + 'fzt_' + image_file)

    def get_best_flat(self, flat_name):
        if os.path.isfile(flat_name):
            try:
                ccd = CCDData.read(flat_name, unit=u.adu)
                return ccd
            except OSError as error:
                log.error(error)
                return False
        else:
            if 'sky.fits' in flat_name:
                flat_name = re.sub('sky.fits', 'dome.fits', flat_name)
            elif 'dome.fits' in flat_name:
                flat_name = re.sub('dome.fits', 'sky.fits', flat_name)
            try:
                ccd = CCDData.read(flat_name, unit=u.adu)
                return ccd
            except OSError as error:
                log.error(error)
                return False

if __name__ == '__main__':
    from night_organizer import Night
    from ccdproc import ImageFileCollection
    keywords = ['date',
                'slit',
                'date-obs',
                'obstype',
                'object',
                'exptime',
                'obsra',
                'obsdec',
                'grating',
                'cam_targ',
                'grt_targ',
                'filter',
                'filter2']
    path = '/data/simon/data/soar/work/image_processor_data_test/imaging/'
    # path = '/data/simon/data/soar/work/image_processor_data_test/spectroscopy_day_flat/'
    # path = '/data/simon/data/soar/work/image_processor_data_test/spectroscopy_night_flat/'
    ic = ImageFileCollection(path, keywords)
    pandas_df = ic.summary.to_pandas()

    if 'imaging' in path:
        night_object = Night(path, 'Red', 'Imaging')
        bias_list = pandas_df[pandas_df.obstype == 'BIAS']
        # print(bias_list)
        night_object.add_bias(bias_list)
        all_flats_list = pandas_df[pandas_df.obstype == 'FLAT']
        # print(all_flats_list['filter'][pandas_df.obstype == 'FLAT'].unique())
        for i_filter in pandas_df['filter'][pandas_df.obstype == 'FLAT'].unique():
            flat_group = all_flats_list[all_flats_list['filter'] == i_filter]
            night_object.add_day_flats(flat_group)
            # print(flat_group)
            # print(all_flats_list[all_flats_list.filter == i_filter])
        all_objects = pandas_df[pandas_df.obstype == 'OBJECT']
        for o_filter in pandas_df['filter'][pandas_df.obstype == 'OBJECT'].unique():
            object_group = all_objects[all_objects['filter'] == o_filter]
            night_object.add_data_group(object_group)
            # print(object_group)

    improc = ImageProcessor(night_object)
    improc()

