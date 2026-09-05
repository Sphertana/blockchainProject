# Shared Azure settings. Override any of these via environment variables.
RG="${AZ_RG:-classledger-rg}"
LOCATION="${AZ_LOCATION:-francecentral}"
VM="${AZ_VM:-classledger-vm}"
VM_SIZE="${AZ_VM_SIZE:-Standard_B2ms}"   # 2 vCPU / 8 GB — fits 4 Besu nodes + API
ADMIN="${AZ_ADMIN:-azureuser}"           # must match cloud-init.yaml
