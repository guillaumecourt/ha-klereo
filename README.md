# Klereo - Home Assistant Integration

Integration Home Assistant pour les systemes de gestion de piscine Klereo. Se connecte a l'API cloud Klereo pour exposer capteurs, controles et consignes dans Home Assistant.

## Fonctionnalites

- **Capteurs** : temperature eau/air, pH, redox, chlore, pression, conductivite, niveau d'eau
- **Capteurs calcules** : volumes dosage pH/chlore, temps filtration/chauffage/electrolyse, production electrolyse
- **Capteurs de mode** : mode piscine, traitement, pH, chauffage
- **Estimation bidons** : volume restant et jours restants avant changement (pH- et chlore)
- **Alertes** : compteur d'alertes avec messages en attributs
- **Selecteurs** : mode filtration (Off/Vitesse 1-3/Auto), eclairage (6 modes), chauffage (Stop/Auto/Cooling/Heating)
- **Interrupteurs** : controle on/off de toutes les sorties (eclairage, filtration, pH, chlore, chauffage, auxiliaires...)
- **Consignes** : curseurs temperature eau, pH, redox, chlore + vitesse pompe
- **Boutons** : reinitialisation des bidons pH- et chlore avec notification de confirmation
- **Multi-piscine** : decouverte automatique des piscines
- **Diagnostics** : export de donnees avec masquage des informations sensibles

## Installation

### Via HACS (recommande)

1. Ouvrez HACS dans Home Assistant
2. Cliquez sur **Integrations** > menu 3 points > **Depots personnalises**
3. Ajoutez `https://github.com/guillaumecourt/ha-klereo` en categorie **Integration**
4. Cherchez "Klereo" dans HACS et installez
5. Redemarrez Home Assistant
6. Allez dans **Parametres > Appareils & Services > + Ajouter une integration**
7. Cherchez "Klereo" et entrez vos identifiants

### Installation manuelle

1. Copiez le dossier `custom_components/klereo/` dans votre repertoire `config/custom_components/`
2. Redemarrez Home Assistant
3. Allez dans **Parametres > Appareils & Services > + Ajouter une integration**
4. Cherchez "Klereo" et entrez vos identifiants

## Configuration

- **Identifiant** : votre login Klereo
- **Mot de passe** : votre mot de passe Klereo
- **Selection piscine** : automatique si une seule, choix si plusieurs
- **Intervalle de mise a jour** : configurable dans les options (defaut: 900 secondes)

## Entites creees

### Capteurs (sensor)

| Entity ID | Description | Unite |
|-----------|-------------|-------|
| `sensor.{pool}_water_temp` | Temperature eau | C |
| `sensor.{pool}_air_temp` | Temperature air | C |
| `sensor.{pool}_ph` | pH | - |
| `sensor.{pool}_redox` | Potentiel redox | mV |
| `sensor.{pool}_chlorine` | Chlore libre | mg/L |
| `sensor.{pool}_water_level` | Niveau d'eau | - |
| `sensor.{pool}_pressure` | Pression filtre | mbar |
| `sensor.{pool}_conductivity` | Conductivite | uS/cm |
| `sensor.{pool}_ph_volume_today` | Volume pH dose aujourd'hui | L |
| `sensor.{pool}_ph_volume_total` | Volume pH dose total | L |
| `sensor.{pool}_chlorine_volume_today` | Volume chlore aujourd'hui | L |
| `sensor.{pool}_chlorine_volume_total` | Volume chlore total | L |
| `sensor.{pool}_filtration_time_today` | Temps filtration aujourd'hui | h |
| `sensor.{pool}_filtration_time_total` | Temps filtration total | h |
| `sensor.{pool}_pool_mode` | Mode piscine | - |
| `sensor.{pool}_treatment_mode` | Mode traitement | - |
| `sensor.{pool}_ph_mode` | Mode pH | - |
| `sensor.{pool}_heater_mode` | Mode chauffage | - |
| `sensor.{pool}_alerts` | Nombre d'alertes | - |
| `sensor.{pool}_container_remaining_ph_minus` | Volume restant bidon pH- | L |
| `sensor.{pool}_container_remaining_chlorine` | Volume restant bidon chlore | L |
| `sensor.{pool}_container_days_remaining_ph_minus` | Jours restants bidon pH- | d |
| `sensor.{pool}_container_days_remaining_chlorine` | Jours restants bidon chlore | d |

### Selecteurs (select)

| Entity ID | Description |
|-----------|-------------|
| `select.{pool}_filtration` | Mode filtration (Off, Vitesse 1-3, Automatique) |
| `select.{pool}_eclairage` | Mode eclairage (6 modes) |
| `select.{pool}_heating_mode` | Mode chauffage (Stop, Auto, Cooling, Heating) |

### Interrupteurs (switch)

| Entity ID | Description |
|-----------|-------------|
| `switch.{pool}_lighting` | Eclairage |
| `switch.{pool}_filtration` | Filtration |
| `switch.{pool}_ph_minus` | pH Moins |
| `switch.{pool}_chlorine` | Chlore |
| `switch.{pool}_electrolysis` | Electrolyse |
| `switch.{pool}_heating` | Chauffage |
| `switch.{pool}_auxiliary_1` a `_4` | Auxiliaires |

### Consignes (number)

| Entity ID | Description | Plage |
|-----------|-------------|-------|
| `number.{pool}_water_temp_setpoint` | Consigne temperature | 10 - 40 C |
| `number.{pool}_ph_setpoint` | Consigne pH | 6.0 - 8.0 |
| `number.{pool}_redox_setpoint` | Consigne redox | 400 - 900 mV |
| `number.{pool}_chlorine_setpoint` | Consigne chlore | 0.0 - 5.0 mg/L |
| `number.{pool}_pump_speed` | Vitesse pompe | 0 - max |
| `number.{pool}_capacity_ph_minus` | Capacite bidon pH- | 1 - 200 L |
| `number.{pool}_capacity_chlorine` | Capacite bidon chlore | 1 - 200 L |

### Boutons (button)

| Entity ID | Description |
|-----------|-------------|
| `button.{pool}_reset_ph_container` | Reinitialiser bidon pH- |
| `button.{pool}_reset_chlorine_container` | Reinitialiser bidon chlore |

> `{pool}` = nom slugifie de votre piscine (ex: "Ma Piscine" -> `ma_piscine`)

## Licence

MIT
