# Linee guida di annotazione: gold standard degli attributi (task B3)

## Cosa si annota

Ogni riga è una coppia di attributi (colonne) provenienti da due tabelle sorgente di MEDITA. Si decide se i due attributi rappresentano **la stessa variabile**.

Il criterio operativo è questo: se le due tabelle venissero impilate, i valori dei due attributi potrebbero stare nella **stessa colonna** senza cambiare significato, unità di misura o livello di dettaglio.

Per decidere si usano il nome grezzo (`raw_*`), il nome normalizzato (`attr_*`), gli esempi di valori (`examples_*`) e l'indicatore di provenienza (`var_code_*`). Non si consulta `cols_attributes.json`: il gold standard serve anche a valutare il dizionario stesso.

## Etichette

| Etichetta | Quando |
|---|---|
| `MATCH` | Stessa variabile: stesso concetto, stessa unità, stessa granularità. Cambiano solo nome, abbreviazione, ortografia o codifica del nome. |
| `NON_MATCH` | Concetti diversi, anche se i nomi sono quasi identici. |
| `INCERTO` | Non decidibile nemmeno con gli esempi. Va sempre spiegato in `NOTE`. Le coppie incerte vengono escluse dal gold standard e contate a parte. |

## Regole di decisione

**1. Abbreviazioni e varianti grafiche sono MATCH.**
- `CODASL` / `CODICE_AZIENDA` → MATCH, se gli esempi sono codici azienda.
- `PARTITAIVA` / `PARTITA_IVA` → MATCH.
- `TIME_PERIOD` / `ANNO` → MATCH, se gli esempi sono anni.

**2. Sottoinsieme contro totale è NON_MATCH.**
- `MEDICI` / `MEDICI_D` → NON_MATCH (totale contro sole donne).
- `TEMPO_PIENO_D` / `TEMPO_PIENO_U` → NON_MATCH (donne contro uomini), anche se la similarità è sopra il 90%.
- `PERSONALE_INFERMIERISTICO` / `INFERMIERI` → MATCH solo se entrambi sono totali.

**3. Codice e descrizione sono NON_MATCH.**
- `CODICE_REGIONE` / `REGIONE` → NON_MATCH (010 contro PIEMONTE).
- `ITTER107` / `ITTER107_DESC` → NON_MATCH.

**4. Stesso concetto con unità o scala diversa è NON_MATCH.**
- Spesa in euro contro spesa in migliaia di euro → NON_MATCH. Se l'unità non si capisce dagli esempi, usare `INCERTO`.

**5. Stesso concetto con granularità diversa è NON_MATCH.**
- Codice ASL contro codice struttura → NON_MATCH.
- Regione contro provincia → NON_MATCH.

**6. Stessa entità con codifica diversa è MATCH.**
- Codice regione ISTAT (`ITC1`) contro codice regione ministeriale (`010`) → MATCH. L'allineamento dei valori è compito dell'armonizzazione, non del matching degli attributi. Scrivere "codifica diversa" in `NOTE`.

**7. Misure diverse dello stesso fenomeno sono NON_MATCH.**
- `NUMERO_DI_ACCESSI_*` / `NUMERO_DI_UTENTI_*` → NON_MATCH (accessi contro persone).
- `GIORNATE_DEGENZA` / `DEGENZA_MEDIA` → NON_MATCH.

**8. Suffissi numerici e residui di parsing vanno giudicati sul contenuto.**
- `NUMERO_DI_ACCESSI_SEMIRESIDENZIALE_DSM` / `NUMERO_DI_ACCESSI_SEMIRESIDENZIALE_DSM1`: se gli esempi hanno lo stesso ordine di grandezza e il suffisso è un artefatto, è MATCH. Annotare "suffisso spurio" in `NOTE`.
- Suffissi che indicano un anno o una classe (`_2021`, `_0_14`) → NON_MATCH, salvo che l'anno sia l'unica differenza tra due edizioni della stessa variabile. In quel caso MATCH, con la nota "anno nel nome".

## Procedura

1. A1 annota l'intero file `annotation_A1.xlsx`.
2. A2 annota `annotation_A2.xlsx` (circa 100 coppie) senza vedere le etichette di A1.
3. Si lancia lo step `agreement`, che calcola il kappa e genera `adjudication.xlsx` con i disaccordi.
4. A1 e A2 discutono ogni disaccordo e scrivono l'etichetta concordata nella colonna `FINAL`.
5. Si rilancia `agreement`, che produce `gold_standard.csv` e `gold_standard_report.json`.

Annotare in sessioni di 50–80 coppie al massimo, per limitare l'affaticamento. Se una regola non copre un caso, aggiungerla qui con un esempio prima di proseguire, così A2 lavora con le stesse regole.

