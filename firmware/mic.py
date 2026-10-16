"""Fábrica de micrófonos: devuelve el adaptador que corresponde a config.MIC_TYPE.

    "adc"  -> mic_adc.AdcMicrophone   (MAX4466 analógico)
    "i2s"  -> mic_i2s.I2sMicrophone   (INMP441 digital)

Cada adaptador se importa solo si se usa, para no cargar (ni depender de) el hardware que no está.
"""

import config


def create_microphone(kind=None):
    kind = kind or config.MIC_TYPE
    if kind == "adc":
        from mic_adc import AdcMicrophone
        return AdcMicrophone()
    if kind == "i2s":
        from mic_i2s import I2sMicrophone
        return I2sMicrophone()
    raise ValueError("MIC_TYPE desconocido: %r (usa 'adc' o 'i2s')" % (kind,))
