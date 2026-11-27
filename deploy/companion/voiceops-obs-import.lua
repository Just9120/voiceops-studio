local obs = obslua
local ffi = require("ffi")
ffi.cdef[[
typedef struct { uint32_t first; uint16_t second; uint16_t third; uint8_t rest[8]; } voiceops_guid;
long CoCreateGuid(voiceops_guid *guid);
int MultiByteToWideChar(unsigned int page, unsigned long flags, const char *input,
                        int length, wchar_t *output, int capacity);
intptr_t ShellExecuteW(void *window, const wchar_t *verb, const wchar_t *file,
                       const wchar_t *args, const wchar_t *directory, int show);
int GetEnvironmentVariableW(const wchar_t *name, wchar_t *value, unsigned long capacity);
int WideCharToMultiByte(unsigned int page, unsigned long flags, const wchar_t *input,
                        int length, char *output, int capacity, const char *replacement, int *substituted);
]]

local kernel = ffi.load("kernel32")
local shell = ffi.load("shell32")
local ole = ffi.load("ole32")
local enabled, track = false, 1
local current = nil

local function wide(value)
    local count = kernel.MultiByteToWideChar(65001, 8, value, -1, nil, 0)
    assert(count > 0)
    local result = ffi.new("wchar_t[?]", count)
    assert(kernel.MultiByteToWideChar(65001, 8, value, -1, result, count) == count)
    return result
end

local function local_appdata()
    local buffer = ffi.new("wchar_t[32768]")
    local count = kernel.GetEnvironmentVariableW(wide("LOCALAPPDATA"), buffer, 32768)
    assert(count > 0 and count < 32768)
    local bytes = kernel.WideCharToMultiByte(65001, 0, buffer, count, nil, 0, nil, nil)
    assert(bytes > 0)
    local result = ffi.new("char[?]", bytes)
    assert(kernel.WideCharToMultiByte(65001, 0, buffer, count, result, bytes, nil, nil) == bytes)
    return ffi.string(result, bytes)
end

local function uuid()
    local guid = ffi.new("voiceops_guid[1]")
    assert(ole.CoCreateGuid(guid) == 0)
    local value = guid[0]
    local parts = { string.format("%08x%04x%04x", value.first, value.second, value.third) }
    for index = 0, 7 do
        parts[#parts + 1] = string.format("%02x", value.rest[index])
    end
    return table.concat(parts)
end

local function launch(arguments)
    local program = script_path() .. "VoiceOpsCompanion.exe"
    assert(obs.os_file_exists(program))
    assert(tonumber(shell.ShellExecuteW(nil, wide("open"), wide(program), wide(arguments), nil, 0)) > 32)
end

local function enqueue(recording, path)
    assert(path ~= "" and not path:find("[\r\n]"))
    local queue = local_appdata() .. "\\VoiceOpsStudio\\local-worker\\obs-import"
    assert(obs.os_mkdirs(queue) == 0 or obs.os_file_exists(queue))
    local entry = queue .. "\\" .. recording.id .. ".pending"
    local payload = string.format("voiceops-obs-import-v1\n%d\n%d\n%s\n", recording.track, recording.started, path)
    assert(obs.os_quick_write_utf8_file(entry .. ".new", payload, #payload, false))
    assert(obs.os_rename(entry .. ".new", entry) == 0)
    launch("--obs-import " .. recording.id)
end

local function normalized(path)
    return (path or ""):gsub("/", "\\"):lower()
end

local function mark_stop(data)
    if current then
        current.clean = obs.calldata_int(data, "code") == 0
    end
end

local function release_recording()
    local recording = current
    current = nil
    if recording then
        obs.signal_handler_disconnect(recording.signals, "stop", mark_stop)
        obs.obs_output_release(recording.output)
    end
    return recording
end

local function on_event(event)
    if event == obs.OBS_FRONTEND_EVENT_RECORDING_STARTED and enabled then
        release_recording()
        local profile = obs.obs_frontend_get_profile_config()
        if not profile then return end
        if obs.config_get_string(profile, "Output", "Mode") == "Advanced"
                and obs.config_get_bool(profile, "AdvOut", "RecSplitFile") then
            obs.script_log(obs.LOG_WARNING, "VoiceOps: отключите разбиение записи на файлы для автоматического импорта.")
            return
        end
        local output = obs.obs_frontend_get_recording_output()
        if not output then return end
        local settings = obs.obs_output_get_settings(output)
        local path = obs.obs_data_get_string(settings, "path")
        if not path or path == "" then path = obs.obs_data_get_string(settings, "url") end
        obs.obs_data_release(settings)
        if not path or path == "" then
            obs.obs_output_release(output)
            return
        end
        local signals = obs.obs_output_get_signal_handler(output)
        current = { id = uuid(), started = os.time() - 1, path = path, track = track, clean = false,
                    output = output, signals = signals }
        obs.signal_handler_connect(signals, "stop", mark_stop)
    elseif event == obs.OBS_FRONTEND_EVENT_RECORDING_STOPPED then
        local recording = release_recording()
        if not enabled or not recording or not recording.clean then return end
        local path = obs.obs_frontend_get_last_recording()
        if normalized(path) ~= normalized(recording.path) then
            obs.script_log(obs.LOG_WARNING, "VoiceOps: OBS закрыл другой файл. Проверьте разбиение или конвертацию записи.")
            return
        end
        if not pcall(enqueue, recording, path) then
            obs.script_log(obs.LOG_WARNING, "VoiceOps: не удалось запустить импорт. Проверьте установку и повторите импорт.")
        end
    end
end

function script_description()
    return "VoiceOps Studio — импорт аудио после остановки записи. Транскрибация запускается вручную в Studio."
end

function script_defaults(settings)
    obs.obs_data_set_default_bool(settings, "enabled", false)
    obs.obs_data_set_default_int(settings, "track", 1)
end

function script_properties()
    local props = obs.obs_properties_create()
    obs.obs_properties_add_bool(props, "enabled", "Импортировать аудио после остановки записи")
    obs.obs_properties_add_int(props, "track", "Номер аудиодорожки в файле", 1, 6, 1)
    return props
end

function script_update(settings)
    enabled = obs.obs_data_get_bool(settings, "enabled")
    track = obs.obs_data_get_int(settings, "track")
    if not enabled then release_recording() end
end

function script_load(settings)
    script_update(settings)
    obs.obs_frontend_add_event_callback(on_event)
end

function script_unload()
    obs.obs_frontend_remove_event_callback(on_event)
    release_recording()
end
