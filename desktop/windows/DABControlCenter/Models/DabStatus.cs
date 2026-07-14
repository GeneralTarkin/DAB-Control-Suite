namespace DABControlCenter.Models;

public sealed class DabStatus
{
    public bool Connected { get; init; }
    public string StationName { get; init; } = "No station selected";
    public string Radiotext { get; init; } = "No radiotext available";
    public string Ensemble { get; init; } = "—";
    public string Frequency { get; init; } = "—";
    public int Rssi { get; init; }
    public int Snr { get; init; }
    public int FicQuality { get; init; }
    public bool StreamRunning { get; init; }
    public string StreamUrl { get; init; } = "";
    public string ErrorMessage { get; init; } = "";
}
