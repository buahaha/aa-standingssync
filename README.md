# standingssync

This is a plugin app for [Alliance Auth](https://gitlab.com/allianceauth/allianceauth), which enables non-alliance characters like scout alts to have the same standings view in game as their alliance main.

[![release](https://img.shields.io/pypi/v/aa-standingssync?label=release)](https://pypi.org/project/aa-standingssync/)
[![python](https://img.shields.io/pypi/pyversions/aa-standingssync)](https://pypi.org/project/aa-standingssync/)
[![django](https://img.shields.io/pypi/djversions/aa-standingssync?label=django)](https://pypi.org/project/aa-standingssync/)
[![pipeline](https://gitlab.com/ErikKalkoken/aa-standingssync/badges/master/pipeline.svg)](https://gitlab.com/ErikKalkoken/aa-standingssync/-/pipelines)
[![codecov](https://codecov.io/gl/ErikKalkoken/aa-standingssync/branch/master/graph/badge.svg?token=gHBi42fbSs)](https://codecov.io/gl/ErikKalkoken/aa-standingssync)
[![license](https://img.shields.io/badge/license-MIT-green)](https://gitlab.com/ErikKalkoken/aa-standingssync/-/blob/master/LICENSE)
[![pre-commit](https://img.shields.io/badge/pre--commit-enabled-brightgreen?logo=pre-commit&logoColor=white)](https://github.com/pre-commit/pre-commit)
[![Code style: black](https://img.shields.io/badge/code%20style-black-000000.svg)](https://github.com/psf/black)
[![chat](https://img.shields.io/discord/790364535294132234)](https://discord.gg/zmh52wnfvM)

## Content

- [Features](#features)
- [Screenshot](#screenshot)
- [How it works](#how-it-works)
- [Installation](#installation)
- [Updating](#updating)
- [Settings](#settings)
- [Permissions](#permissions)
- [Admin Functions](#Admin-functions)
- [Feedback](#feedback)
- [Change Log](CHANGELOG.md)

## Features

The main purpose of this app is to enable non-alliance characters to have the same standings view of other pilots in game as their alliance main. This e.g. allows non-alliance scouts to correctly report blues and non-blues. And is allows JF pilots to, which other non-alliance characters on grid are actually blues and which are not and therefore a potential threat.

Here is an high level overview of the main features:

- Synchronize alliance contacts to chosen non-alliance characters
- Synchronization is ongoing until user chooses to remove character from synchronization
- Supports multiple alliances
- Can sync war targets
- Synchronization automatically ceases once the user is no longer eligible

## Screenshot

Here is a screenshot of the main screen.

![Main Screen](https://i.imgur.com/xGdoqsp.png)

## How it works

To enable non-alliance members to use alliance standings the personal contact of that character are replaced with the alliance contacts.

## Installation

### 1. Install app

Install into AA virtual environment with PIP install ffrom PyPI:

```bash
pip install aa-standingssync
```

### 2 Update Eve Online app

Update the Eve Online app used for authentication in your AA installation to include the following scopes:

```plain
esi-characters.read_contacts.v1
esi-characters.write_contacts.v1
esi-alliances.read_contacts.v1
```

### 3. Configure AA settings

Configure your AA settings (`local.py`) as follows:

- Add `'standingssync'` to `INSTALLED_APPS`
- Add these lines add to bottom of your settings file:

   ```python
   # settings for standingssync
   CELERYBEAT_SCHEDULE['standingssync.run_regular_sync'] = {
       'task': 'standingssync.tasks.run_regular_sync',
       'schedule': crontab(minute=0, hour='*/2')
   }
   ```

   > **Note**:<br>This configures the sync process to run every 2 hours starting at 00:00 AM UTC. Feel free to adjust the timing to the needs of you alliance.<br>However, do not schedule it too tightly. Or you risk generating more and more tasks, when sync tasks from previous runs are not able to finish within the alloted time.

### 4. Finalize installation into AA

Run migrations & copy static files

```bash
python manage.py migrate
python manage.py collectstatic
```

Restart your supervisor services for AA

### 5. Setup permissions

Now you can access Alliance Auth and setup permissions for your users. See section "Permissions" below for details.

### 6. Setup alliance character

Finally you need to set the alliance character that will be used for fetching the alliance contacts / standing. Just click on "Set Alliance Character" and add the requested token. Note that only users with the appropriate permission will be able to see and use this function.

Once an alliance character is set the app will immediately start fetching alliance contacts. Wait a minute and then reload the page to see the result.

That's it. The Standing Sync app is fully installed and ready to be used.

## Updating

To update your existing installation of Alliance Freight first enable your virtual environment.

Then run the following commands from your AA project directory (the one that contains `manage.py`).

```bash
pip install -U aa-standingssync
```

```bash
python manage.py migrate
```

```bash
python manage.py collectstatic
```

Finally restart your AA supervisor services.

## Settings

Here is a list of available settings for this app. They can be configured by adding them to your AA settings file (`local.py`). If they are not set the defaults are used.

Name | Description | Default
-- | -- | --
`STANDINGSSYNC_ADD_WAR_TARGETS`| When enabled will automatically add current war targets with -10 standing to synced characters | `False`
`STANDINGSSYNC_CHAR_MIN_STANDING`| minimum standing a character needs to have with the alliance to be able to sync.<br>Set to `0.0` if you want to allow neutral alts to sync. | `0.1`<br>*character has to have some blue standing, neutrals will be rejected*
`STANDINGSSYNC_REPLACE_CONTACTS`| When enabled will replace contacts of synced characters with alliance contacts | `True`
`STANDINGSSYNC_WAR_TARGETS_LABEL_NAME`| Name of the contact label for war targets. Needs to be created by the user for each synced character. Required to ensure that war targets are deleted once they become invalid. Not case sensitive. | `war_targets`

## Permissions

This app only uses two permission. One for enabling this app for users and one for enabling users to add alliances for syncing.

Name | Purpose | Code
-- | -- | --
Can add synced character |Enabling the app for a user. This permission should be enabled for everyone who is allowed to use the app (e.g. Member state) |  `add_syncedcharacter`
Can add alliance manager |Enables adding alliances for syncing by setting the character for fetching alliance contacts. This should be limited to users with admins / leadership privileges. |  `add_syncmanager`

## Admin functions

Admins will find a "Standings Sync" section on the admin page. This section provides the following features:

- See a list of all setup alliances with their sync status

- See a list of all enabled characters with their current sync status

- Manually remove characters / alliances from sync

- Manually start the sync process for characters / alliances

## Feedback

If you encounter any bugs or would like to request a new feature please open an issue in this gitlab repo.
