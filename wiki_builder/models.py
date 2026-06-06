# gnammyAssistant/wiki_builder/models.py
import re
import unicodedata
from enum import Enum
from pydantic import BaseModel, Field, computed_field


def slugify(text: str) -> str:
    normalized = unicodedata.normalize("NFKD", text)
    ascii_text = normalized.encode("ascii", "ignore").decode("ascii")
    lower = ascii_text.lower()
    slug = re.sub(r"[^\w\s-]", "", lower)
    slug = re.sub(r"[\s_]+", "-", slug)
    slug = re.sub(r"-+", "-", slug).strip("-")
    return slug


class EntityType(str, Enum):
    ingredient = "ingredient"
    dish = "dish"
    region = "region"
    technique = "technique"
    product = "product"
    chef = "chef"
    other = "other"


class ConceptType(str, Enum):
    technique = "technique"
    flavor_profile = "flavor_profile"
    dietary_pattern = "dietary_pattern"
    food_science = "food_science"
    cultural = "cultural"
    occasion = "occasion"
    other = "other"


class ExtractedEntity(BaseModel):
    name: str
    type: EntityType
    aliases: list[str] = Field(default_factory=list)
    summary: str = ""
    mentions_in_source: list[str] = Field(default_factory=list)
    related_entities: list[str] = Field(default_factory=list)
    related_concepts: list[str] = Field(default_factory=list)

    @computed_field
    @property
    def slug(self) -> str:
        return slugify(self.name)


class ExtractedConcept(BaseModel):
    name: str
    type: ConceptType
    aliases: list[str] = Field(default_factory=list)
    definition: str = ""
    key_characteristics: list[str] = Field(default_factory=list)
    applications: list[str] = Field(default_factory=list)
    mentions_in_source: list[str] = Field(default_factory=list)
    related_concepts: list[str] = Field(default_factory=list)
    related_entities: list[str] = Field(default_factory=list)

    @computed_field
    @property
    def slug(self) -> str:
        return slugify(self.name)


class SourceExtractionResult(BaseModel):
    recipe_id: str
    source_title: str
    entities: list[ExtractedEntity] = Field(default_factory=list)
    concepts: list[ExtractedConcept] = Field(default_factory=list)
