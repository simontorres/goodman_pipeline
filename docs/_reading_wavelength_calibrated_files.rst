.. _reading-wavelength-calibrated-files:

Read Wavelength Calibrated Files
********************************

.. important::

  This change was introduced in :ref:`v3.0.0` as a consequence of several requirements received
  requesting to eliminate resampling of the wavelength calibrated data. It introduces breaking changes
  for instance the wavelength calibrated file is no longer stored as a linear wavelength solution,
  instead it creates a FITS Binary Table.


FITS File Structure
^^^^^^^^^^^^^^^^^^^

Getting The Spectrum
^^^^^^^^^^^^^^^^^^^^

Recreate Mathematical Model
^^^^^^^^^^^^^^^^^^^^^^^^^^^
