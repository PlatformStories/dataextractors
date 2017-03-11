import sys
from setuptools import setup, find_packages

open_kwds = {}
if sys.version_info > (3,):
    open_kwds['encoding'] = 'utf-8'

# with open('README.md', **open_kwds) as f:
#     readme = f.read()

# long_description=readme,

setup(name='dataextractors',
      version='0.0.2',
      description='Extract pixels and metadata using shapefiles and georeferenced imagery.',
      classifiers=[],
      keywords='',
      author='Nikki Aldeborgh',
      author_email='nikki.aldeborgh@digitalglobe.com',
      url='https://github.com/platformstories/dataextractors',
      license='MIT',
      packages=find_packages(),
      include_package_data=True,
      zip_safe=False,
      install_requires=['geoio >= 1.1.1',
                        'geojson >= 1.3.2',
                        'numpy >= 1.12.0',
                        'scikit-learn >= 0.17.1',
                        'bumpversion'
                        ]
      )
