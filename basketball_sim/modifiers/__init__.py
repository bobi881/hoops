"""Realism modifier layers.

Each modifier is an independent function: ActionContext in, Modifier out.
No modifier knows other modifiers exist. The pipeline combines them additively.
"""
