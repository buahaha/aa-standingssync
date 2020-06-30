# Change Log

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](http://keepachangelog.com/)
and this project adheres to [Semantic Versioning](http://semver.org/).

## [Unreleased] - yyyy-mm-dd

## [1.1.1] - 2020-06-30

### Changed

- Update to Font Awesome v5. Thank you Peter Pfeufer for your contribution! 

## [1.1.0] - 2020-05-28

### Changed

- Drops support for Python 3.5
- Updated dependency for django-esi to exclude 2.0
- Added timeout to ESI requests

## [1.0.4] - 2020-04-19

### Fixed

- New attempt to reduce the memory leaks in celery workers

## [1.0.3] - 2020-04-12

### Changed

- Sync status now updated at the end of the process, not at the beginning

### Fixed

- Corrected required permission for adding sync managers
- Minor bugfixes
- Improved test coverage

## [1.0.2] - 2020-02-28

### Added

- Version number for this app now shown on admin site

### Fixed

- Bug: Standing value was sometimes not synced correctly for contacts

## [1.0.1] - 2019-12-19

### Changed

- Improved error handling of contacts sync process
- Improved layout of messages

## [1.0.0] - 2019-10-02

### Added

- First release
