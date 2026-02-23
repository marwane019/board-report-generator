#!/usr/bin/env bash
# =============================================================================
# azure/provision.sh — One-time Azure infrastructure provisioning
#
# Run this ONCE before your first GitHub Actions deployment.
# After this script completes, add the printed values as GitHub Secrets and
# push to main — the CI/CD pipeline handles everything from there.
#
# Prerequisites:
#   - Azure CLI installed  (https://docs.microsoft.com/en-us/cli/azure/install-azure-cli)
#   - Authenticated        (az login)
#   - Active subscription  (az account show)
#
# Usage:
#   bash azure/provision.sh                          # Default resource names
#   WEBAPP_NAME=my-unique-name bash azure/provision.sh  # Custom webapp name
#
# Resources created (estimated monthly cost):
#   Azure Container Registry Basic  ~$5 USD/month
#   App Service Plan B1 (Linux)     ~$13 USD/month
#   App Service (Web App)           $0 (included in plan)
#   Resource Group                  $0
#                                   ─────────────────
#   Total                           ~$18 USD/month
#
# To destroy all resources when no longer needed:
#   az group delete --name rg-board-report --yes --no-wait
# =============================================================================

set -euo pipefail

# ── Configuration (override via environment variables) ────────────────────────
RESOURCE_GROUP="${RESOURCE_GROUP:-rg-board-report}"
LOCATION="${LOCATION:-uksouth}"                      # UK South — closest to Europe/London
ACR_NAME="${ACR_NAME:-boardreportacr}"               # Must be globally unique, no hyphens
APP_SERVICE_PLAN="${APP_SERVICE_PLAN:-asp-board-report}"
# WEBAPP_NAME must be globally unique — forms part of *.azurewebsites.net URL
WEBAPP_NAME="${WEBAPP_NAME:-board-report-generator-app}"
SKU="${SKU:-B1}"                                     # B1 required for Always On
SP_NAME="${SP_NAME:-sp-board-report-cicd}"           # Service principal for GitHub Actions

# ── Colour helpers ────────────────────────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; BLUE='\033[0;34m'; NC='\033[0m'
info()    { echo -e "${BLUE}▶${NC}  $*"; }
success() { echo -e "${GREEN}✓${NC}  $*"; }
warn()    { echo -e "${YELLOW}⚠${NC}  $*"; }
error()   { echo -e "${RED}✗${NC}  $*" >&2; }
banner()  { echo -e "\n${BLUE}══════════════════════════════════════════════════════${NC}"; \
            echo -e "${BLUE}  $*${NC}"; \
            echo -e "${BLUE}══════════════════════════════════════════════════════${NC}\n"; }

# ── Pre-flight checks ─────────────────────────────────────────────────────────
banner "Board Report Generator — Azure Provisioning"

if ! command -v az &>/dev/null; then
    error "Azure CLI not found. Install from https://aka.ms/installazurecli"
    exit 1
fi

if ! az account show &>/dev/null; then
    error "Not logged in. Run: az login"
    exit 1
fi

SUBSCRIPTION_ID=$(az account show --query id --output tsv)
SUBSCRIPTION_NAME=$(az account show --query name --output tsv)
info "Subscription: ${SUBSCRIPTION_NAME} (${SUBSCRIPTION_ID})"
info "Resource group: ${RESOURCE_GROUP}  |  Location: ${LOCATION}"
info "ACR: ${ACR_NAME}  |  Plan: ${APP_SERVICE_PLAN} (${SKU})  |  App: ${WEBAPP_NAME}"
echo ""
read -rp "Proceed with provisioning? [y/N] " confirm
[[ "${confirm}" =~ ^[Yy]$ ]] || { warn "Aborted."; exit 0; }
echo ""

# ── Step 1/7: Resource group ──────────────────────────────────────────────────
info "[1/7] Resource group: ${RESOURCE_GROUP}"
if az group show --name "${RESOURCE_GROUP}" &>/dev/null; then
    warn "Resource group already exists — skipping creation"
else
    az group create \
        --name "${RESOURCE_GROUP}" \
        --location "${LOCATION}" \
        --output none
    success "Resource group created"
fi

# ── Step 2/7: Azure Container Registry ────────────────────────────────────────
info "[2/7] Azure Container Registry: ${ACR_NAME} (Basic tier)"
if az acr show --name "${ACR_NAME}" --resource-group "${RESOURCE_GROUP}" &>/dev/null; then
    warn "ACR already exists — skipping creation"
else
    az acr create \
        --resource-group "${RESOURCE_GROUP}" \
        --name "${ACR_NAME}" \
        --sku Basic \
        --admin-enabled true \
        --output none
    success "ACR created: ${ACR_NAME}.azurecr.io"
fi

# ── Step 3/7: App Service Plan ────────────────────────────────────────────────
info "[3/7] App Service Plan: ${APP_SERVICE_PLAN} (${SKU} Linux)"
if az appservice plan show --name "${APP_SERVICE_PLAN}" --resource-group "${RESOURCE_GROUP}" &>/dev/null; then
    warn "App Service Plan already exists — skipping creation"
else
    az appservice plan create \
        --name "${APP_SERVICE_PLAN}" \
        --resource-group "${RESOURCE_GROUP}" \
        --is-linux \
        --sku "${SKU}" \
        --output none
    success "App Service Plan created (${SKU} Linux)"
fi

# ── Step 4/7: Web App for Containers ──────────────────────────────────────────
info "[4/7] Web App: ${WEBAPP_NAME}"
if az webapp show --name "${WEBAPP_NAME}" --resource-group "${RESOURCE_GROUP}" &>/dev/null; then
    warn "Web App already exists — skipping creation"
else
    # Deploying with a public placeholder image so the app is immediately
    # reachable. The CI/CD pipeline will replace it with the ACR image.
    az webapp create \
        --name "${WEBAPP_NAME}" \
        --resource-group "${RESOURCE_GROUP}" \
        --plan "${APP_SERVICE_PLAN}" \
        --deployment-container-image-name "mcr.microsoft.com/appsvc/staticsite:latest" \
        --output none
    success "Web App created: https://${WEBAPP_NAME}.azurewebsites.net"
fi

# ── Step 5/7: Configure App Service ───────────────────────────────────────────
info "[5/7] Configuring App Service settings"

# Enable Always On — prevents the container from sleeping between Monday runs.
# Requires B1 or higher; not available on Free (F1) tier.
az webapp config set \
    --name "${WEBAPP_NAME}" \
    --resource-group "${RESOURCE_GROUP}" \
    --always-on true \
    --output none
success "Always On enabled"

# WEBSITES_PORT tells App Service which port the container listens on.
# MPLBACKEND=Agg prevents matplotlib from trying to open a display.
az webapp config appsettings set \
    --name "${WEBAPP_NAME}" \
    --resource-group "${RESOURCE_GROUP}" \
    --settings \
        WEBSITES_PORT=8000 \
        PYTHONUNBUFFERED=1 \
        MPLBACKEND=Agg \
        LOG_LEVEL=INFO \
    --output none
success "App settings configured"

# Grant the Web App permission to pull images from ACR using admin credentials.
# For production at scale, replace with Managed Identity:
#   az webapp identity assign --name $WEBAPP_NAME --resource-group $RESOURCE_GROUP
#   az role assignment create --assignee <principalId> --role AcrPull --scope <acrId>
ACR_LOGIN_SERVER=$(az acr show --name "${ACR_NAME}" --query loginServer --output tsv)
ACR_CREDS=$(az acr credential show --name "${ACR_NAME}")
ACR_USERNAME=$(echo "${ACR_CREDS}" | python3 -c "import sys,json; print(json.load(sys.stdin)['username'])")
ACR_PASSWORD=$(echo "${ACR_CREDS}" | python3 -c "import sys,json; print(json.load(sys.stdin)['passwords'][0]['value'])")

az webapp config container set \
    --name "${WEBAPP_NAME}" \
    --resource-group "${RESOURCE_GROUP}" \
    --docker-custom-image-name "${ACR_LOGIN_SERVER}/board-report-generator:latest" \
    --docker-registry-server-url "https://${ACR_LOGIN_SERVER}" \
    --docker-registry-server-user "${ACR_USERNAME}" \
    --docker-registry-server-password "${ACR_PASSWORD}" \
    --output none
success "ACR pull credentials configured"

# ── Step 6/7: Configure health-check path ─────────────────────────────────────
info "[6/7] Configuring App Service health check probe"
az webapp config set \
    --name "${WEBAPP_NAME}" \
    --resource-group "${RESOURCE_GROUP}" \
    --health-check-path "/health" \
    --output none 2>/dev/null || warn "Health check path config requires az CLI ≥ 2.40; set manually in portal if needed"
success "Health check path: /health"

# ── Step 7/7: Create Service Principal for GitHub Actions ─────────────────────
info "[7/7] Creating Service Principal for CI/CD: ${SP_NAME}"
SCOPE="/subscriptions/${SUBSCRIPTION_ID}/resourceGroups/${RESOURCE_GROUP}"

# Check if SP already exists
EXISTING_SP=$(az ad sp list --display-name "${SP_NAME}" --query "[0].appId" --output tsv 2>/dev/null || true)
if [[ -n "${EXISTING_SP}" && "${EXISTING_SP}" != "None" ]]; then
    warn "Service principal '${SP_NAME}' already exists (appId: ${EXISTING_SP})"
    warn "To rotate credentials: az ad sp credential reset --id ${EXISTING_SP} --sdk-auth"
    SP_JSON="(existing SP — reset credentials if needed)"
else
    SP_JSON=$(az ad sp create-for-rbac \
        --name "${SP_NAME}" \
        --role contributor \
        --scopes "${SCOPE}" \
        --sdk-auth)
    success "Service principal created"
fi

# ── Output: GitHub Secrets to copy ────────────────────────────────────────────
banner "Provisioning Complete — Add these GitHub Secrets"

echo -e "${YELLOW}Go to: https://github.com/marwane019/board-report-generator/settings/secrets/actions${NC}"
echo -e "${YELLOW}Click 'New repository secret' for each secret below:${NC}"
echo ""

echo -e "${GREEN}Secret name:${NC} AZURE_CREDENTIALS"
echo -e "${GREEN}Secret value:${NC}"
echo "${SP_JSON}"
echo ""

echo -e "${GREEN}Secret name:${NC} ACR_LOGIN_SERVER"
echo -e "${GREEN}Secret value:${NC} ${ACR_LOGIN_SERVER}"
echo ""

echo -e "${GREEN}Secret name:${NC} ACR_USERNAME"
echo -e "${GREEN}Secret value:${NC} ${ACR_USERNAME}"
echo ""

echo -e "${GREEN}Secret name:${NC} ACR_PASSWORD"
echo -e "${GREEN}Secret value:${NC} ${ACR_PASSWORD}"
echo ""

echo -e "${GREEN}Secret name:${NC} AZURE_WEBAPP_NAME  (used in workflow env.AZURE_WEBAPP_NAME)"
echo -e "${GREEN}Secret value:${NC} ${WEBAPP_NAME}"
echo ""

echo -e "${YELLOW}Optional secrets (enables email and Slack — pipeline runs in dry-run if absent):${NC}"
echo "  SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASSWORD"
echo "  SLACK_WEBHOOK_URL"
echo ""

echo -e "${BLUE}App Service URL:${NC} https://${WEBAPP_NAME}.azurewebsites.net"
echo -e "${BLUE}ACR URL:${NC}         https://${ACR_LOGIN_SERVER}"
echo ""

echo -e "${GREEN}Next step:${NC} git push origin main"
echo "  The GitHub Actions workflow will build the Docker image, push to ACR,"
echo "  and deploy to App Service automatically."
echo ""

# ── Sanity check — verify resources exist ────────────────────────────────────
info "Final resource check:"
az resource list \
    --resource-group "${RESOURCE_GROUP}" \
    --query "[].{Name:name, Type:type}" \
    --output table
