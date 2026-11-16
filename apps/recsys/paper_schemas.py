"""Shared presentation schemas; scoring remains a task/type setting."""

PAPER_CONFIG = {
    'rows': 1, 'cols': 17, 'input_type': 'char', 'per_cell_max_length': 1,
    'auto_advance': True, 'backspace': 'previous_cell', 'allow_blank_cells': True,
}
FREE_CONFIG = {
    'rows': 1, 'cols': 1, 'input_type': 'text', 'ui_hint': 'textarea', 'manual_check': True,
}

LEGACY_PHYSICS_SCHEMAS = {
    '3 цифры по порядку': {'cols': 3, 'input_type': 'char', 'per_cell_max_length': 1, 'digits_only': True},
    '4 цифры по порядку': {'cols': 4, 'input_type': 'char', 'per_cell_max_length': 1, 'digits_only': True},
    '2 цифры по порядку': {'cols': 2, 'input_type': 'char', 'per_cell_max_length': 1, 'digits_only': True},
    'Выбор двух цифр': {'cols': 2, 'input_type': 'char', 'per_cell_max_length': 1, 'digits_only': True, 'allow_blank_cells': True},
    'Одна цифра': {'cols': 1, 'input_type': 'char', 'per_cell_max_length': 1, 'digits_only': True},
    'Числовой ответ': {'cols': 1, 'input_type': 'float'},
    'Развёрнутый ответ': {k: v for k, v in FREE_CONFIG.items() if k != 'rows'},
}
