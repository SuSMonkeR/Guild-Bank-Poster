-- GBankExporterAddon.lua v2.2
-- Scans bags and bank, exports per-character inventory data to SavedVariables.
-- Compatible with WoW Classic Era 1.15.x (C_Container API)
--
-- Usage:
--   /gbankexport         scan and save
--   /gbankexport reload  scan, save, and ReloadUI
--
-- Bags are always scanned. Bank slots are only included if the bank window
-- is currently open (WoW doesn't load bank contents otherwise).
-- Open your bank first for a complete export.

GBankExporterDB = GBankExporterDB or {}

-- ─── Category classification ─────────────────────────────────────────────────

local CATEGORY_ORDER = {
    "Consumables", "Containers", "Weapons", "Armor",
    "Reagents", "Trade Goods", "Recipes", "Miscellaneous",
}

local CATEGORY_MAP = {
    [0]  = "Consumables",
    [1]  = "Containers",
    [2]  = "Weapons",
    [4]  = "Armor",
    [5]  = "Reagents",
    [7]  = "Trade Goods",
    [9]  = "Recipes",
    [15] = "Reagents",
}

local function getCategory(itemID)
    if not itemID then return "Miscellaneous" end
    local classID = select(12, GetItemInfo(itemID))
    return CATEGORY_MAP[classID] or "Miscellaneous"
end

-- ─── Container API compat shim ───────────────────────────────────────────────

local function getNumSlots(bag)
    if C_Container and C_Container.GetContainerNumSlots then
        return C_Container.GetContainerNumSlots(bag) or 0
    end
    return GetContainerNumSlots(bag) or 0
end

local function getItemLink(bag, slot)
    if C_Container and C_Container.GetContainerItemLink then
        return C_Container.GetContainerItemLink(bag, slot)
    end
    return GetContainerItemLink(bag, slot)
end

local function getItemCount(bag, slot)
    if C_Container and C_Container.GetContainerItemInfo then
        local info = C_Container.GetContainerItemInfo(bag, slot)
        return (info and info.stackCount) or 1
    end
    local _, count = GetContainerItemInfo(bag, slot)
    return count or 1
end

-- ─── Scanning ────────────────────────────────────────────────────────────────

local function isBankOpen()
    return BankFrame and BankFrame:IsShown()
end

local function scanBag(bag, items)
    local slots = getNumSlots(bag)
    for slot = 1, slots do
        local link = getItemLink(bag, slot)
        if link then
            local count  = getItemCount(bag, slot)
            local itemID = tonumber(link:match("item:(%d+)"))
            if itemID then
                local name = GetItemInfo(itemID)
                       or link:match("%[(.-)%]")
                       or ("item:" .. itemID)
                local key = tostring(itemID)
                if items[key] then
                    items[key].count = items[key].count + count
                else
                    items[key] = { id = itemID, name = name, count = count,
                                   category = getCategory(itemID) }
                end
            end
        end
    end
end

local function scanAll()
    local items    = {}
    local bankDone = false

    -- Always scan character bags (backpack + 4 bag slots)
    for bag = 0, 4 do
        scanBag(bag, items)
    end

    -- Scan bank only if the window is open
    if isBankOpen() then
        scanBag(-1, items)          -- main bank container
        for bag = 5, 11 do          -- bank bag slots
            scanBag(bag, items)
        end
        bankDone = true
    end

    return items, bankDone
end

-- ─── Serialisation ───────────────────────────────────────────────────────────

local function buildBlob(items)
    local buckets = {}
    for _, cat in ipairs(CATEGORY_ORDER) do buckets[cat] = {} end

    for _, data in pairs(items) do
        local cat = buckets[data.category] and data.category or "Miscellaneous"
        table.insert(buckets[cat], data.id .. "|" .. data.name .. "|" .. data.count)
    end

    local lines = {}
    for _, cat in ipairs(CATEGORY_ORDER) do
        if #buckets[cat] > 0 then
            table.insert(lines, "##CATEGORY:" .. cat)
            table.sort(buckets[cat])
            for _, entry in ipairs(buckets[cat]) do
                table.insert(lines, entry)
            end
        end
    end

    return table.concat(lines, "\n")
end

-- ─── Export ──────────────────────────────────────────────────────────────────

local function doExport(doReload)
    local playerName = UnitName("player")
    local realmName  = GetRealmName()
    local charKey    = playerName .. "-" .. realmName

    local items, bankIncluded = scanAll()
    local blob  = buildBlob(items)

    GBankExporterDB[charKey] = {
        updated_at = time(),
        character  = playerName,
        realm      = realmName,
        blob       = blob,
    }

    local count = 0
    for _ in pairs(items) do count = count + 1 end

    if bankIncluded then
        print(string.format(
            "|cff89b4faGBankExporter:|r Exported %d unique item types for %s (bags + bank).",
            count, charKey))
    else
        print(string.format(
            "|cff89b4faGBankExporter:|r Exported %d unique item types for %s (bags only).",
            count, charKey))
        print("|cfffab387GBankExporter:|r Open the bank window and run again to include bank contents.")
    end

    if doReload then ReloadUI() end
end

-- ─── Slash commands ──────────────────────────────────────────────────────────

SLASH_GBANKEXPORT1 = "/gbankexport"

SlashCmdList["GBANKEXPORT"] = function(msg)
    msg = msg and msg:lower():match("^%s*(.-)%s*$") or ""
    if msg == "reload" then
        doExport(true)
    else
        doExport(false)
    end
end
