from setuptools import setup, find_packages


setup(
    name='wialond',
    version='0.7',
    packages=find_packages(),
    install_requires=[
        'chronometer>=1.0',
        'PyYAML>=3.12',
        'gps',
    ],
)
