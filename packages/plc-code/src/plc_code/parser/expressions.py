"""AST d'expressions pour SCL.

Dimensionné sur la mesure, pas sur la référence du langage : sur 14 217 tranches
d'expression dans cinq projets de production, l'accès (`#`, `.`, `[]`) domine
largement, puis l'arithmétique, puis le booléen. `XOR` n'apparaît pas une seule
fois et n'a pas de nœud ici — le parseur le signale comme erreur, ce qui est la
réponse honnête pour une construction que l'outillage ne traduit pas.

Les nœuds sont gelés : un arbre qu'un consommateur peut muter n'est plus une
lecture de la source.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Literal:
    """Un littéral : nombre, chaîne, ``TRUE``/``FALSE``.

    Attributes
    ----------
    line, column : int
        Position du premier token dans la source.
    value : str
        Le texte du littéral, tel qu'écrit.
    """

    line: int
    column: int
    value: str


@dataclass(frozen=True)
class TypedLiteral:
    """Un littéral préfixé par son type : ``T#5s``, ``16#FF``, ``DINT#5``.

    Le lexer ne les reconnaît pas ; il produit la même suite de tokens qu'un
    accès variable précédé d'un nombre ou d'un identifiant. Sans ce nœud,
    ``16#FF`` se lit « 16 puis la variable ``#FF`` », silencieusement.

    Attributes
    ----------
    line, column : int
        Position du préfixe dans la source.
    prefix : str
        Ce qui précède le ``#`` : ``"T"``, ``"16"``, ``"DINT"``.
    value : str
        Ce qui suit le ``#``, concaténé tel quel : ``"5s"``, ``"FF"``.
    """

    line: int
    column: int
    prefix: str
    value: str


@dataclass(frozen=True)
class VariableRef:
    """Une variable : ``#local`` ou ``"DbName"``.

    Attributes
    ----------
    line, column : int
        Position dans la source.
    name : str
        Le nom, sans le ``#`` ni les guillemets.
    is_local : bool
        True pour ``#name`` (variable du bloc), False pour ``"name"`` (bloc de
        données ou bloc global). La distinction est celle que le générateur doit
        faire pour choisir entre un attribut d'instance et une recherche globale.
    """

    line: int
    column: int
    name: str
    is_local: bool


@dataclass(frozen=True)
class Member:
    """Un accès membre : ``base.name``.

    Attributes
    ----------
    line, column : int
        Position du ``.`` dans la source.
    base : Expression
        Ce sur quoi porte l'accès.
    name : str
        Le nom du membre.
    """

    line: int
    column: int
    base: Expression
    name: str


@dataclass(frozen=True)
class Index:
    """Une indexation : ``base[index]``.

    Attributes
    ----------
    line, column : int
        Position du ``[`` dans la source.
    base : Expression
        Ce qui est indexé.
    index : Expression
        L'indice, lui-même une expression.
    """

    line: int
    column: int
    base: Expression
    index: Expression


@dataclass(frozen=True)
class UnaryOp:
    """Un opérateur unaire : ``NOT x``, ``-x``.

    Attributes
    ----------
    line, column : int
        Position de l'opérateur.
    operator : str
        ``"NOT"`` (en majuscules) ou ``"-"``.
    operand : Expression
        L'opérande.
    """

    line: int
    column: int
    operator: str
    operand: Expression


@dataclass(frozen=True)
class BinaryOp:
    """Un opérateur binaire.

    Attributes
    ----------
    line, column : int
        Position de l'opérateur.
    operator : str
        La forme SCL composée : ``"+"``, ``"*"``, ``">="``, ``"<>"``, ``"**"``,
        ``"AND"``, ``"OR"``, ``"MOD"``. Les mots sont en majuscules.
    left, right : Expression
        Les opérandes.
    """

    line: int
    column: int
    operator: str
    left: Expression
    right: Expression


@dataclass(frozen=True)
class FunctionCall:
    """Un appel de fonction dans une expression : ``ABS(#x)``, ``INT_TO_REAL(#n)``.

    Attributes
    ----------
    line, column : int
        Position du nom de la fonction.
    name : str
        Le nom, tel qu'écrit.
    arguments : list[Expression]
        Les arguments, dans l'ordre source.
    """

    line: int
    column: int
    name: str
    arguments: list[Expression] = field(default_factory=list)


Expression = (
    Literal | TypedLiteral | VariableRef | Member | Index | UnaryOp | BinaryOp | FunctionCall
)
