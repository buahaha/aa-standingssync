from typing import Tuple, List

from django.db import models, transaction
from django.utils.timezone import now

from allianceauth.services.hooks import get_extension_logger

from . import __title__
from .providers import esi
from .utils import LoggerAddTag


logger = LoggerAddTag(get_extension_logger(__name__), __title__)


class AllianceContactManager(models.Manager):
    def grouped_by_standing(self, sync_manager: object) -> dict:
        """returns alliance contacts grouped by their standing as dict"""

        contacts_by_standing = dict()
        for contact in self.filter(manager=sync_manager):
            if contact.standing not in contacts_by_standing:
                contacts_by_standing[contact.standing] = set()
            contacts_by_standing[contact.standing].add(contact)

        return contacts_by_standing


class EveEntityManager(models.Manager):
    def get_or_create_from_esi_info(self, info) -> Tuple[models.Model, bool]:
        """returns an EveEntity object for the given esi info
        will return existing or create new one if needed
        """
        id = info.get("alliance_id") or info.get("corporation_id")
        category = (
            self.model.Category.ALLIANCE
            if info.get("alliance_id")
            else self.model.Category.CORPORATION
        )
        return self.get_or_create(id=id, defaults={"category": category})


class EveWarManager(models.Manager):
    def active_wars(self) -> models.QuerySet:
        return self.filter(started__lt=now(), finished__gt=now()) | self.filter(
            started__lt=now(), finished__isnull=True
        )

    def finished_wars(self) -> models.QuerySet:
        return self.filter(finished__lte=now())

    def delete_outdated(self):
        to_be_deleted = list(self.order_by("-id")[2000:])
        return self.filter(pk__in=to_be_deleted).delete()

    def war_targets(self, alliance_id: int) -> List[models.Model]:
        """returns list of current war targets for given alliance as EveEntity objects
        or an empty list if there are none
        """
        war_targets = list()
        active_wars = self.active_wars()
        # case 1 alliance is aggressor
        for war in active_wars:
            if war.aggressor.eve_entity_id == alliance_id:
                war_targets.append(war.defender.eve_entity)
                if war.allies:
                    war_targets += list(war.allies.all())

        # case 2 alliance is defender
        for war in active_wars:
            if war.defender.eve_entity_id == alliance_id:
                war_targets.append(war.aggressor.eve_entity)

        # case 3 alliance is ally
        for war in active_wars:
            if war.allies.filter(id=alliance_id).exists():
                war_targets.append(war.aggressor.eve_entity)

        return war_targets

    def update_from_esi(self, id: int):
        from .models import EveWarProtagonist, EveEntity

        logger.info("Retrieving war details for ID %s", id)
        war_info = esi.client.Wars.get_wars_war_id(war_id=id).results()
        logger.info("Updating war details for ID %s", id)
        with transaction.atomic():
            self.filter(id=id).delete()
            aggressor = EveWarProtagonist.objects.create_from_esi_info(
                war_info.get("aggressor")
            )
            defender = EveWarProtagonist.objects.create_from_esi_info(
                war_info.get("defender")
            )
            war = self.create(
                id=id,
                aggressor=aggressor,
                declared=war_info.get("declared"),
                defender=defender,
                is_mutual=war_info.get("mutual"),
                is_open_for_allies=war_info.get("open_for_allies"),
                retracted=war_info.get("retracted"),
                started=war_info.get("started"),
                finished=war_info.get("finished"),
            )
            if war_info.get("allies"):
                for ally_info in war_info.get("allies"):
                    eve_entity = EveEntity.objects.get_or_create_from_esi_info(
                        ally_info
                    )[0]
                    war.allies.add(eve_entity)


class EveWarProtagonistManager(models.Manager):
    def create_from_esi_info(self, info) -> models.Model:
        from .models import EveEntity

        return self.create(
            eve_entity=EveEntity.objects.get_or_create_from_esi_info(info)[0],
            isk_destroyed=info.get("isk_destroyed"),
            ships_killed=info.get("ships_killed"),
        )


class SyncManagerManager(models.Manager):
    pass
