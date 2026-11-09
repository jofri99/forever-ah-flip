local ADDON_NAME = ...

local HEADER = "index,itemID,itemString,name,quality,count,minBid,buyout,bidAmount,owner,timeLeft,level,isCommodity"
local MAX_RETRIES = 3
local RETRY_DELAY = 3
local TIMEOUT = 120

local f = CreateFrame("Frame")
local scanning, retries = false, 0
local commodityCache = {}

local function Print(msg)
	print("|cff33ff99AHDump|r: " .. msg)
end

-- CSV-Feld escapen (Komma / Anfuehrungszeichen in Item- oder Spielernamen)
local function Csv(v)
	if v == nil then return "" end
	local s = tostring(v)
	if s:find('[,"\n\r]') then
		return '"' .. s:gsub('"', '""') .. '"'
	end
	return s
end

-- Bei Commodities ist der Buyout-Preis ein Stueckpreis, bei normalen
-- Auktionen der Preis fuer den kompletten Stack. Ohne diese Info laesst
-- sich kein sauberer Preis pro Einheit berechnen.
local function IsCommodity(itemID)
	if not itemID then return nil end
	local cached = commodityCache[itemID]
	if cached ~= nil then return cached end

	if not C_AuctionHouse.GetItemKeyInfo then return nil end
	local ok, info = pcall(C_AuctionHouse.GetItemKeyInfo, {
		itemID = itemID,
		itemLevel = 0,
		itemSuffix = 0,
		battlePetSpeciesID = 0,
	})
	if ok and info then
		cached = info.isCommodity and 1 or 0
		commodityCache[itemID] = cached
		return cached
	end
	return nil
end

local function Collect()
	local num = C_AuctionHouse.GetNumReplicateItems() or 0
	local rows, missing = {}, 0

	for i = 0, num - 1 do
		local name, _, count, quality, _, level, _, minBid, _, buyout,
		      bidAmount, _, _, owner, _, itemID, hasAllInfo = C_AuctionHouse.GetReplicateItemInfo(i)

		if not hasAllInfo then
			missing = missing + 1
			if itemID and C_Item and C_Item.RequestLoadItemDataByID then
				C_Item.RequestLoadItemDataByID(itemID)
			end
		end

		local link = C_AuctionHouse.GetReplicateItemLink(i)
		local itemString = link and link:match("item[%-%d:]+") or ""
		local timeLeft = C_AuctionHouse.GetReplicateItemTimeLeft(i)
		local commodity = IsCommodity(itemID)
		if commodity == nil then missing = missing + 1 end

		rows[#rows + 1] = table.concat({
			i,
			itemID or "",
			Csv(itemString),
			Csv(name),
			quality or "",
			count or "",
			minBid or 0,
			buyout or 0,
			bidAmount or 0,
			Csv(owner),
			timeLeft or "",
			level or "",
			commodity or "",
		}, ",")
	end

	return rows, missing, num
end

local function Stop()
	scanning = false
	f:UnregisterEvent("REPLICATE_ITEM_LIST_UPDATE")
end

local function Step()
	if not scanning then return end

	local rows, missing, num = Collect()

	-- Items, deren Daten noch nicht im Cache sind, nach kurzer Pause nachziehen
	if missing > 0 and retries < MAX_RETRIES then
		retries = retries + 1
		Print(string.format("%d von %d Eintraegen noch unvollstaendig, warte kurz (%d/%d) ...",
			missing, num, retries, MAX_RETRIES))
		C_Timer.After(RETRY_DELAY, Step)
		return
	end

	AHDumpDB.header = HEADER
	AHDumpDB.realm = GetRealmName()
	AHDumpDB.faction = UnitFactionGroup("player")
	AHDumpDB.timestamp = date("%Y-%m-%d %H:%M:%S")
	AHDumpDB.count = #rows
	AHDumpDB.incomplete = missing
	AHDumpDB.rows = rows

	Stop()
	Print(string.format("|cff00ff00%d Auktionen gespeichert|r (%d Felder ohne vollstaendige Daten).", #rows, missing))
	Print("Jetzt |cffffff00/reload|r oder ausloggen - erst dann wird die Datei geschrieben:")
	Print("WTF\Account\<ACCOUNT>\SavedVariables\AHDump.lua")
end

f:RegisterEvent("ADDON_LOADED")
f:SetScript("OnEvent", function(self, event, arg1)
	if event == "ADDON_LOADED" then
		if arg1 == ADDON_NAME then
			AHDumpDB = AHDumpDB or {}
			self:UnregisterEvent("ADDON_LOADED")
		end
	elseif event == "REPLICATE_ITEM_LIST_UPDATE" then
		if not scanning then return end
		Print("Daten vom Server erhalten, verarbeite ...")
		Step()
	end
end)

SLASH_AHDUMP1 = "/ahdump"
SlashCmdList["AHDUMP"] = function(msg)
	msg = strtrim((msg or "")):lower()

	if msg == "clear" then
		AHDumpDB = {}
		Print("Daten geleert - nach /reload ist die Datei leer.")
		return
	end

	if msg == "info" then
		if AHDumpDB and AHDumpDB.count then
			Print(string.format("Letzter Dump: %s, %s, %d Auktionen.",
				tostring(AHDumpDB.timestamp), tostring(AHDumpDB.realm), AHDumpDB.count))
		else
			Print("Noch kein Dump vorhanden.")
		end
		return
	end

	if scanning then
		Print("Es laeuft bereits ein Scan.")
		return
	end

	if not (C_AuctionHouse and C_AuctionHouse.ReplicateItems) then
		Print("Dieser Client hat keine moderne Auktionshaus-API (C_AuctionHouse).")
		return
	end

	if not (AuctionHouseFrame and AuctionHouseFrame:IsShown()) then
		Print("Hinweis: Das Auktionshaus scheint nicht offen zu sein - der Full-Scan funktioniert nur am Auktionator.")
	end

	scanning, retries = true, 0
	f:RegisterEvent("REPLICATE_ITEM_LIST_UPDATE")
	C_AuctionHouse.ReplicateItems()
	Print("Full-Scan gestartet, das dauert meist 10-60 Sekunden ...")

	C_Timer.After(TIMEOUT, function()
		if scanning then
			Stop()
			Print("|cffff0000Keine Antwort vom Server.|r Der Full-Scan ist serverseitig stark limitiert (ca. alle 15 Minuten einmal) - spaeter nochmal versuchen.")
		end
	end)
end
