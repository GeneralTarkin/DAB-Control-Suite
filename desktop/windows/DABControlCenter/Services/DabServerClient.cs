using System.IO;
using System.Net.Http;
using System.Text.Json;
using DABControlCenter.Models;

namespace DABControlCenter.Services;

public sealed class DabServerClient
{
    private readonly HttpClient _httpClient = new()
    {
        Timeout = TimeSpan.FromSeconds(5)
    };

    public async Task<DabStatus> GetStatusAsync(
        string serverAddress,
        CancellationToken cancellationToken = default)
    {
        string baseAddress = NormalizeBaseAddress(serverAddress);
        string url = $"{baseAddress}/api/status";

        try
        {
            using HttpResponseMessage response =
                await _httpClient.GetAsync(url, cancellationToken);

            response.EnsureSuccessStatusCode();

            await using Stream stream =
                await response.Content.ReadAsStreamAsync(cancellationToken);

            using JsonDocument document =
                await JsonDocument.ParseAsync(stream, cancellationToken: cancellationToken);

            JsonElement root = document.RootElement;

            string stationName =
                ReadString(root, "current", "label")
                ?? ReadString(root, "current", "name")
                ?? ReadString(root, "metadata", "station_text")
                ?? "No station selected";

            string radiotext =
                ReadString(root, "metadata", "dls_interpretation", "display_title")
                ?? ReadString(root, "metadata", "dls", "title")
                ?? ReadString(root, "metadata", "dls", "raw")
                ?? "No radiotext available";

            string ensemble =
                ReadString(root, "metadata", "ensemble_info", "label")
                ?? "—";

            int? frequencyValue =
                ReadInt(root, "metadata", "digrad_status", "tune_freq");

            string frequency =
                frequencyValue is > 0
                    ? $"{frequencyValue.Value / 1000.0:0.000} MHz"
                    : "—";

            int rssi =
                ReadInt(root, "metadata", "digrad_status", "rssi") ?? 0;

            int snr =
                ReadInt(root, "metadata", "digrad_status", "snr") ?? 0;

            int ficQuality =
                ReadInt(root, "metadata", "digrad_status", "FIC_quality") ?? 0;

            bool streamRunning =
                ReadBool(root, "stream_status", "running")
                ?? ReadBool(root, "stream_status", "process_running")
                ?? false;

            string streamUrl =
                ReadString(root, "stream") ?? "";

            return new DabStatus
            {
                Connected = true,
                StationName = string.IsNullOrWhiteSpace(stationName)
                    ? "No station selected"
                    : stationName,
                Radiotext = string.IsNullOrWhiteSpace(radiotext)
                    ? "No radiotext available"
                    : radiotext,
                Ensemble = ensemble,
                Frequency = frequency,
                Rssi = rssi,
                Snr = snr,
                FicQuality = ficQuality,
                StreamRunning = streamRunning,
                StreamUrl = streamUrl
            };
        }
        catch (Exception ex)
        {
            return new DabStatus
            {
                Connected = false,
                ErrorMessage = ex.Message
            };
        }
    }

    private static string NormalizeBaseAddress(string address)
    {
        string value = address.Trim().TrimEnd('/');

        if (!value.StartsWith("http://", StringComparison.OrdinalIgnoreCase) &&
            !value.StartsWith("https://", StringComparison.OrdinalIgnoreCase))
        {
            value = "http://" + value;
        }

        return value;
    }

    private static JsonElement? FindElement(JsonElement root, params string[] path)
    {
        JsonElement current = root;

        foreach (string part in path)
        {
            if (current.ValueKind != JsonValueKind.Object ||
                !current.TryGetProperty(part, out JsonElement next))
            {
                return null;
            }

            current = next;
        }

        return current;
    }

    private static string? ReadString(JsonElement root, params string[] path)
    {
        JsonElement? element = FindElement(root, path);

        if (element is null || element.Value.ValueKind == JsonValueKind.Null)
        {
            return null;
        }

        return element.Value.ValueKind == JsonValueKind.String
            ? element.Value.GetString()
            : element.Value.ToString();
    }

    private static int? ReadInt(JsonElement root, params string[] path)
    {
        JsonElement? element = FindElement(root, path);

        if (element is null)
        {
            return null;
        }

        if (element.Value.ValueKind == JsonValueKind.Number &&
            element.Value.TryGetInt32(out int number))
        {
            return number;
        }

        return int.TryParse(element.Value.ToString(), out int parsed)
            ? parsed
            : null;
    }

    private static bool? ReadBool(JsonElement root, params string[] path)
    {
        JsonElement? element = FindElement(root, path);

        if (element is null)
        {
            return null;
        }

        return element.Value.ValueKind switch
        {
            JsonValueKind.True => true,
            JsonValueKind.False => false,
            _ => bool.TryParse(element.Value.ToString(), out bool parsed)
                ? parsed
                : null
        };
    }
}
