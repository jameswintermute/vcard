# cards-merge

Drop your exported .vcf files from each source into this folder, then run:

    vcard-normalize merge --owner-name "YourName"

## Naming convention (recommended)

| Source          | Filename              |
|-----------------|-----------------------|
| Apple iCloud    | icloud.vcf            |
| Proton Mail     | protonmail.vcf        |
| Google Contacts | google.vcf            |
| Outlook / M365  | outlook.vcf           |
| Other           | anything-you-like.vcf |

The filename stem (e.g. "icloud") is used as a source label in the
processing report so you can see exactly where each contact came from.

## This folder is in .gitignore

Your contact exports are private. The folder itself is tracked (so it exists
on clone), but any .vcf files you place here are ignored by git.
