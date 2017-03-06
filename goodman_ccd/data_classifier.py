from __future__ import print_function
import glob
import re
import random
from ccdproc import ImageFileCollection
import logging
import numpy as np
from astropy.io import fits

log = logging.getLogger('goodmanccd.dataclassifier')


class DataClassifier(object):

    def __init__(self, args):
        self.args = args
        self.nights_dict = None
        self.instrument = None
        self.image_collection = None
        self.objects_collection = None
        self.technique = None

    def __call__(self, *args, **kwargs):
        self.nights_dict = {}
        print(self.args.raw_path)
        self.get_instrument(self.args.raw_path)
        print(self.instrument)
        self.get_obs_technique()
        print(self.technique)
        if self.instrument is not None and self.technique is not None:
            self.nights_dict[self.args.raw_path.split('/')[-1]] = {'full_path': self.args.raw_path,
                                                          'instrument': self.instrument,
                                                          'technique': self.technique}
        else:
            log.error('Failed to determine Instrument or Technique for the night: ' + self.args.raw_path)

        print('END\n')
        # TODO (simon): Remove this cleaning process and modify software so it is not necessary
        self.instrument = None
        self.technique = None

    def get_instrument(self, night_folder):
        while True:
            try:
                ifc = ImageFileCollection(night_folder)
                self.image_collection = ifc.summary.to_pandas()
                self.objects_collection = self.image_collection[self.image_collection.obstype == 'OBJECT']
                print(len(self.objects_collection))
                if len(self.objects_collection) > 0:
                    index = random.choice(self.objects_collection.index.tolist())
                    print('Index: ' + str(index))
                    try:
                        # print(self.objects_collection.instconf[index])
                        self.instrument = self.objects_collection.instconf[index]
                    except AttributeError as error:
                        log.error(error)
                        print(self.objects_collection.file[index])
                        self.instrument = 'Blue'
                else:
                    log.error('There is not data of type OBJECT in this folder.')
            except ValueError as error:
                if 'Inconsistent data column lengths' in str(error):
                    log.error('There are duplicated keywords in the headers. Fix it first!')
                    self.fix_duplicated_keywords(night_folder)
                    continue
                else:
                    log.error('Unknown Error: ' + str(error))
            break

    def get_obs_technique(self):
        if self.instrument == 'Red':
            wavmodes = self.objects_collection.wavmode.unique()
            if len(wavmodes) == 1 and wavmodes[0] == 'Imaging':
                self.technique = 'Imaging'
                log.info('Detected Imaging Data from RED Camera')
            elif 'Imaging' in wavmodes and len(wavmodes) > 1:
                log.error('There are mixed observation techniques this night. Please classify your data')
                self.technique = 'Unknown'
            else:
                self.technique = 'Spectroscopy'
                log.info('Detected Spectroscopy Data from RED Camera')
        elif self.instrument == 'Blue':
            self.remove_conflictive_keywords()
            gratings = self.objects_collection.grating.unique()
            if gratings != ['<NO GRATING>']:
                self.technique = 'Spectroscopy'
                log.info('Detected Spectroscopy Data from BLUE Camera')
            elif gratings == ['<NO GRATING>'] and int(np.mean(self.objects_collection.cam_targ.unique())) == 0:
                self.technique = 'Imaging'
                log.info('Detected Imaging Data from BLUE Camera')
            else:
                log.error('It was not possible to determine observing technique')
                self.technique = 'Unknown'

    @staticmethod
    def fix_duplicated_keywords(night_dir):
        files = glob.glob(night_dir + '/*.fits')
        random_file = random.choice(files)
        random_header = fits.getheader(random_file)
        multiple_keys = []
        for keyword in random_header.keys():
            if keyword != '':
                if random_header.count(keyword) > 1:
                    if keyword not in multiple_keys:
                        multiple_keys.append(keyword)
        if multiple_keys != []:
            for image_file in files:
                try:
                    print(image_file)
                    hdu = fits.open(image_file)
                    for keyword in multiple_keys:
                        while hdu[0].header.count(keyword) > 1:
                            hdu[0].header.remove(keyword, hdu[0].header.count(keyword) - 1)
                    log.warning('Overwriting file with duplicated keywords removed')
                    log.info('File %s overwritten', image_file)
                    hdu.writeto(image_file, clobber=True)
                except IOError as error:
                    log.error(error)

    def remove_conflictive_keywords(self):
        for blue_file in self.image_collection.file.tolist():
            full_path = re.sub('//', '/', '/'.join(self.args.raw_path.split('/') + [blue_file]))
            try:
                data, header = fits.getdata(full_path, header=True, ignore_missing_end=True)
                keys_to_remove = ['PARAM0', 'PARAM61', 'PARAM62', 'PARAM63', 'NAXIS3']
                if data.ndim == 3:
                    header['NAXIS'] = 2
                    data = data[0]
                    log.info('Modified file to be 2D instead of 3D (problematic)')
                for keyword in keys_to_remove:
                    header.remove(keyword)
                    log.info('Removed conflictive keyword ' + keyword)
                log.info('Updated headers')
                fits.writeto(full_path, data, header, clobber=True)
            except KeyError as error:
                log.debug(error)



if __name__ == '__main__':
    pass

